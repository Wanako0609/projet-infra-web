"""
Service d'export et d'import d'infrastructures sous forme d'archive .zip déclarative.

Principes de sécurité :
- À l'EXPORT : génère infra.json + configs/<node_id>/... + un docker-compose.yml
  indicatif pour tests locaux hors plateforme.
- À l'IMPORT : format strictement déclaratif (data-only). Tout script (.sh) ou
  docker-compose.yml présent dans l'archive est ignoré et jamais exécuté.
  Protection contre le Zip Slip (path traversal), les liens symboliques et les
  zip bombs (plafonds de taille et de nombre de fichiers).
"""

import io
import json
from pathlib import PurePosixPath
import re
import stat
import zipfile

from pydantic import ValidationError

from app.core.catalog import MODULE_CATALOG
from app.schemas.infrastructure import (
    InfraExportManifest,
    InfrastructureDefinition,
    MAX_FILE_CONTENT_BYTES,
)

MAX_ZIP_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 Mo max pour le .zip envoyé
MAX_UNCOMPRESSED_TOTAL_BYTES = 5 * 1024 * 1024  # 5 Mo max une fois décompressé
MAX_ZIP_ENTRIES = 100
MANIFEST_FILENAME = "infra.json"


class ArchiveError(ValueError):
    """Erreur levée lorsqu'une archive .zip importée est invalide ou dangereuse."""


def slugify_filename(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return f"{slug or 'infrastructure'}.zip"


def _yaml_quote(value: str) -> str:
    """Échappe proprement une chaîne pour un fichier YAML sans dépendance externe."""
    return json.dumps(str(value), ensure_ascii=False)


def _generate_docker_compose(name: str, definition: InfrastructureDefinition) -> str:
    """
    Génère un docker-compose.yml indicatif à partir du catalogue vérifié.
    Ce fichier est fourni à l'export pour pouvoir tester localement hors plateforme,
    mais il est systématiquement ignoré lors d'un import sur la plateforme.
    """
    lines = [
        f"# Infrastructure : {name}",
        "# Fichier généré automatiquement par la plateforme pour lancement local uniquement.",
        "# ATTENTION : ce fichier est ignoré lors de l'import sur la plateforme (seuls infra.json et configs/ sont lus).",
        "",
        "services:",
    ]

    if not definition.nodes:
        lines.append("  # Aucun module défini dans cette infrastructure")
    else:
        for node in definition.nodes:
            spec = MODULE_CATALOG[node.module_type]
            cfg = {**spec["default_config"], **(node.config or {})}
            lines.append(f"  {node.id}:")
            lines.append(f"    image: {_yaml_quote(spec['docker_image'])}")
            lines.append(f"    mem_limit: {_yaml_quote(spec['memory_limit'])}")

            hostname = cfg.get("hostname") or node.id
            lines.append(f"    hostname: {_yaml_quote(hostname)}")

            if node.module_type == "postgres":
                lines.append("    environment:")
                lines.append(f"      POSTGRES_DB: {_yaml_quote(cfg.get('db_name', 'app_db'))}")
                lines.append(f"      POSTGRES_USER: {_yaml_quote(cfg.get('db_user', 'postgres'))}")
                lines.append(f"      POSTGRES_PASSWORD: {_yaml_quote(cfg.get('db_password', 'password'))}")

            if node.files:
                lines.append("    volumes:")
                if node.module_type == "postgres":
                    lines.append(f"      - ./configs/{node.id}:{spec['workspace_path']}:ro")
                else:
                    lines.append(f"      - ./configs/{node.id}/workspace:{spec['workspace_path']}")

            lines.append("    networks:")
            lines.append("      - infra_net")

    lines.extend(
        [
            "",
            "networks:",
            "  infra_net:",
            "    driver: bridge",
            "",
        ]
    )
    return "\n".join(lines)


def _generate_readme(name: str, description: str) -> str:
    return (
        f"Infrastructure exportée : {name}\n"
        f"{description}\n\n"
        "Contenu de cette archive :\n"
        "- infra.json         : définition déclarative (modules, positions, liens, paramètres)\n"
        "- configs/<id>/      : fichiers associés aux modules (ex. init.sql, workspace/...)\n"
        "- docker-compose.yml : fichier généré pour test local hors plateforme\n\n"
        "Sécurité & ré-import sur la plateforme :\n"
        "Lors de l'import, la plateforme ne lit QUE infra.json et configs/.\n"
        "Tout script ou docker-compose.yml est ignoré et n'est jamais exécuté.\n"
        "En V1, les paquets système installés manuellement hors /workspace ne sont pas exportés.\n"
    )


def build_infra_zip(
    name: str,
    description: str,
    definition: InfrastructureDefinition,
) -> tuple[bytes, str]:
    """
    Construit une archive .zip en mémoire contenant infra.json, configs/<node_id>/...,
    docker-compose.yml et README.txt.
    """
    # Dans infra.json, on n'embarque pas le contenu brut de files pour éviter la duplication :
    # les fichiers vivent directement sous configs/<node_id>/<rel_path> (éditables facilement).
    definition_without_inline_files = InfrastructureDefinition(
        schema_version=definition.schema_version,
        nodes=[node.model_copy(update={"files": {}}) for node in definition.nodes],
        links=definition.links,
    )
    manifest = InfraExportManifest(
        schema_version="1.0",
        name=name,
        description=description,
        definition=definition_without_inline_files,
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            MANIFEST_FILENAME,
            json.dumps(manifest.model_dump(), indent=2, ensure_ascii=False) + "\n",
        )

        for node in definition.nodes:
            for rel_path, content in node.files.items():
                archive_path = f"configs/{node.id}/{rel_path}"
                zf.writestr(archive_path, content.encode("utf-8"))

        zf.writestr("docker-compose.yml", _generate_docker_compose(name, definition))
        zf.writestr("README.txt", _generate_readme(name, description))

    return buffer.getvalue(), slugify_filename(name)


def _validate_zip_entry_path(raw_name: str) -> PurePosixPath:
    """Vérifie qu'un chemin d'entrée ZIP ne contient aucune tentative de Zip Slip."""
    if not raw_name or raw_name.startswith("/") or "\\" in raw_name or "\x00" in raw_name:
        raise ArchiveError(f"Chemin interdit dans l'archive : '{raw_name}'.")
    path = PurePosixPath(raw_name)
    if any(part in ("..", "") for part in path.parts):
        raise ArchiveError(f"Tentative de traversée de répertoire détectée (Zip Slip) : '{raw_name}'.")
    return path


def _read_entry_bounded(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    max_file_bytes: int,
    remaining_total_bytes: int,
) -> bytes:
    """
    Lit une entrée ZIP par blocs plafonnés pour neutraliser les zip bombs même si
    l'en-tête file_size de l'archive a été falsifié.
    """
    limit = min(max_file_bytes, remaining_total_bytes)
    chunks: list[bytes] = []
    total_read = 0
    with zf.open(info, mode="r") as stream:
        while True:
            chunk = stream.read(16_384)
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > limit:
                raise ArchiveError(
                    f"L'archive ou le fichier '{info.filename}' dépasse la limite de taille autorisée."
                )
            chunks.append(chunk)
    return b"".join(chunks)


def parse_infra_zip(raw_bytes: bytes) -> InfraExportManifest:
    """
    Lit et valide strictement une archive .zip importée par un utilisateur.
    Ne lit que infra.json et configs/<node_id>/... ; ignore tout autre fichier.
    """
    if len(raw_bytes) > MAX_ZIP_UPLOAD_BYTES:
        raise ArchiveError(
            f"Archive trop volumineuse (maximum {MAX_ZIP_UPLOAD_BYTES // (1024 * 1024)} Mo)."
        )

    try:
        zf = zipfile.ZipFile(io.BytesIO(raw_bytes), mode="r")
    except zipfile.BadZipFile as exc:
        raise ArchiveError("Le fichier fourni n'est pas une archive .zip valide.") from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise ArchiveError(f"L'archive contient trop de fichiers (maximum {MAX_ZIP_ENTRIES}).")

        manifest_bytes: bytes | None = None
        config_files_by_node: dict[str, dict[str, str]] = {}
        total_uncompressed = 0

        for info in infos:
            # Bloque les liens symboliques à l'intérieur du ZIP
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise ArchiveError(f"Lien symbolique interdit dans l'archive : '{info.filename}'.")

            if info.is_dir():
                _validate_zip_entry_path(info.filename.rstrip("/") or "dir")
                continue

            path = _validate_zip_entry_path(info.filename)
            parts = path.parts

            # Ignore les métadonnées macOS et tout fichier hors infra.json / configs/
            if parts[0] == "__MACOSX":
                continue

            if path.as_posix() == MANIFEST_FILENAME:
                remaining = MAX_UNCOMPRESSED_TOTAL_BYTES - total_uncompressed
                manifest_bytes = _read_entry_bounded(zf, info, 512_000, remaining)
                total_uncompressed += len(manifest_bytes)
                continue

            if parts[0] == "configs":
                if len(parts) < 3:
                    raise ArchiveError(
                        f"Structure attendue sous configs/ : configs/<node_id>/<fichier> (reçu '{info.filename}')."
                    )
                node_id = parts[1]
                rel_path = PurePosixPath(*parts[2:]).as_posix()
                remaining = MAX_UNCOMPRESSED_TOTAL_BYTES - total_uncompressed
                file_bytes = _read_entry_bounded(zf, info, MAX_FILE_CONTENT_BYTES, remaining)
                total_uncompressed += len(file_bytes)
                try:
                    content = file_bytes.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ArchiveError(
                        f"Le fichier '{info.filename}' doit être un fichier texte encodé en UTF-8."
                    ) from exc
                config_files_by_node.setdefault(node_id, {})[rel_path] = content
                continue

            # Tous les autres fichiers (docker-compose.yml, README.txt, scripts .sh...)
            # sont volontairement ignorés par mesure de sécurité.

    if manifest_bytes is None:
        raise ArchiveError(f"Fichier '{MANIFEST_FILENAME}' manquant à la racine de l'archive.")

    try:
        raw_manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveError(f"Le fichier '{MANIFEST_FILENAME}' n'est pas un JSON UTF-8 valide.") from exc

    try:
        manifest = InfraExportManifest.model_validate(raw_manifest)
    except ValidationError as exc:
        first_msg = exc.errors()[0].get("msg", "Structure invalide")
        raise ArchiveError(f"Manifeste invalide : {first_msg}") from exc

    # Associe les fichiers de configs/<node_id>/... aux nœuds déclarés dans infra.json
    nodes_by_id = {node.id: node for node in manifest.definition.nodes}
    for node_id, files in config_files_by_node.items():
        if node_id not in nodes_by_id:
            raise ArchiveError(
                f"Le dossier 'configs/{node_id}/' ne correspond à aucun module déclaré dans {MANIFEST_FILENAME}."
            )
        merged_files = {**nodes_by_id[node_id].files, **files}
        nodes_by_id[node_id] = nodes_by_id[node_id].model_copy(update={"files": merged_files})

    # Revalidation complète de l'ensemble (nœuds + fichiers fusionnés + liens)
    try:
        final_definition = InfrastructureDefinition.model_validate(
            {
                "schema_version": manifest.definition.schema_version,
                "nodes": [nodes_by_id[node.id].model_dump() for node in manifest.definition.nodes],
                "links": [link.model_dump() for link in manifest.definition.links],
            }
        )
    except ValidationError as exc:
        first_msg = exc.errors()[0].get("msg", "Validation échouée")
        raise ArchiveError(f"Fichiers de configuration invalides : {first_msg}") from exc

    return manifest.model_copy(update={"definition": final_definition})
