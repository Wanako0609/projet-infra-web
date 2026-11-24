"""
Moteur d'orchestration Docker (SDK Python docker).

Responsabilités :
- Isoler chaque infrastructure dans un réseau bridge Linux dédié (vrai domaine L2 :
  ARP, MAC, tcpdump/Wireshark) avec allocation dynamique et recyclage des /24.
- Démarrer / arrêter des conteneurs strictement issus de MODULE_CATALOG, avec quotas
  RAM/CPU/PIDs, capabilities minimales et labels de traçabilité.
- Gérer les modules « à la demande » (ex. linux_desktop) indépendamment du démarrage global.
- Matérialiser les fichiers de configuration (init.sql, /workspace) dans backend/.runtime/.
"""

import ipaddress
from pathlib import Path, PurePosixPath
from typing import Any

import docker
from docker.errors import APIError, DockerException, ImageNotFound, NotFound
from docker.types import IPAMConfig, IPAMPool

from app.core.catalog import MODULE_CATALOG
from app.core.config import BACKEND_DIR
from app.schemas.infrastructure import (
    InfrastructureDefinition,
    InfrastructureRuntimeStatus,
    NodeDefinition,
    NodeRuntimeStatus,
)

MANAGED_LABEL = "infra_web.managed"
INFRA_ID_LABEL = "infra_web.infra_id"
NODE_ID_LABEL = "infra_web.node_id"
MODULE_TYPE_LABEL = "infra_web.module_type"

RUNTIME_ROOT = BACKEND_DIR / ".runtime"


class OrchestratorError(RuntimeError):
    """Erreur métier / système remontée par l'orchestrateur Docker."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def network_name_for(infra_id: int) -> str:
    return f"infra_{infra_id}_net"


def container_name_for(infra_id: int, node_id: str) -> str:
    return f"infra_{infra_id}_{node_id}"


def allocate_free_subnet(client: Any) -> ipaddress.IPv4Network:
    """
    Parcourt les réseaux Docker actifs et choisit le premier /24 libre dans
    10.100.1.0/24 .. 10.250.250.0/24 (37 500 sous-réseaux simultanés possibles).
    Les /24 des infrastructures arrêtées sont automatiquement recyclés.
    """
    used_networks: list[ipaddress.IPv4Network] = []
    for net in client.networks.list():
        ipam = (net.attrs or {}).get("IPAM") or {}
        for cfg in ipam.get("Config") or []:
            subnet_str = cfg.get("Subnet")
            if not subnet_str:
                continue
            try:
                parsed = ipaddress.ip_network(subnet_str, strict=False)
                if isinstance(parsed, ipaddress.IPv4Network):
                    used_networks.append(parsed)
            except ValueError:
                continue

    for octet2 in range(100, 251):
        for octet3 in range(1, 251):
            candidate = ipaddress.IPv4Network(f"10.{octet2}.{octet3}.0/24")
            if not any(candidate.overlaps(used) for used in used_networks):
                return candidate

    raise OrchestratorError(
        "Aucun sous-réseau privé libre disponible sur le serveur Docker.",
        status_code=503,
    )


def resolve_node_ip(
    subnet: ipaddress.IPv4Network | None,
    configured_ip: str | None,
    used_ips: set[str],
) -> str | None:
    """
    Si l'utilisateur a précisé une IP dans node.config (ex. 10.10.0.10),
    conserve son dernier octet (.10) dans le /24 alloué à cette infrastructure
    afin de garder des IP lisibles tout en évitant les collisions entre étudiants.
    Si vide ou invalide, renvoie None (Docker IPAM attribue une IP libre automatiquement).
    """
    if subnet is None or not configured_ip:
        return None
    raw = str(configured_ip).strip().split("/")[0]
    if not raw:
        return None

    try:
        parsed = ipaddress.IPv4Address(raw)
        last_octet = int(str(parsed).split(".")[-1])
    except ValueError:
        return None

    # .0 = réseau, .1 = passerelle Docker, .255 = broadcast
    if not (2 <= last_octet <= 254):
        return None

    prefix = ".".join(str(subnet.network_address).split(".")[:3])
    candidate = f"{prefix}.{last_octet}"
    if candidate in used_ips:
        return None
    return candidate


def _extract_network_subnet(network: Any) -> ipaddress.IPv4Network | None:
    ipam = (network.attrs or {}).get("IPAM") or {}
    for cfg in ipam.get("Config") or []:
        subnet_str = cfg.get("Subnet")
        if subnet_str:
            try:
                net = ipaddress.ip_network(subnet_str, strict=False)
                if isinstance(net, ipaddress.IPv4Network):
                    return net
            except ValueError:
                continue
    return None


def _extract_container_ip(container: Any, net_name: str) -> str | None:
    networks = ((container.attrs or {}).get("NetworkSettings") or {}).get("Networks") or {}
    net_info = networks.get(net_name) or {}
    ip = net_info.get("IPAddress")
    return ip or None


def _extract_host_port(container: Any, container_port: int | None) -> int | None:
    if not container_port:
        return None
    ports = ((container.attrs or {}).get("NetworkSettings") or {}).get("Ports") or {}
    bindings = ports.get(f"{container_port}/tcp") or []
    if not bindings:
        return None
    raw_port = bindings[0].get("HostPort")
    return int(raw_port) if raw_port else None


def _safe_write_file(base_dir: Path, rel_path: str, content: str) -> None:
    base_resolved = base_dir.resolve()
    target = (base_resolved / PurePosixPath(rel_path)).resolve()
    if base_resolved not in target.parents:
        raise OrchestratorError(f"Chemin de fichier interdit hors du répertoire runtime : '{rel_path}'.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _prepare_node_volumes(
    infra_id: int,
    node: NodeDefinition,
    spec: dict[str, Any],
    runtime_root: Path = RUNTIME_ROOT,
) -> dict[str, dict[str, str]]:
    """
    Écrit les fichiers déclaratifs du nœud dans backend/.runtime/infra_<id>/<node_id>/
    et renvoie le dictionnaire de volumes attendu par le SDK Docker.
    """
    node_dir = runtime_root / f"infra_{infra_id}" / node.id

    if node.module_type == "postgres":
        if not node.files:
            return {}
        init_dir = node_dir / "initdb"
        init_dir.mkdir(parents=True, exist_ok=True)
        for rel_path, content in node.files.items():
            # Ne jamais placer de script .sh dans /docker-entrypoint-initdb.d/
            parts = PurePosixPath(rel_path).parts
            if len(parts) != 1 or not rel_path.lower().endswith(".sql"):
                raise OrchestratorError(
                    f"Fichier interdit pour PostgreSQL (seuls les '.sql' sont autorisés) : '{rel_path}'."
                )
            _safe_write_file(init_dir, rel_path, content)
        return {
            str(init_dir.resolve()): {
                "bind": spec["workspace_path"],
                "mode": "ro",
            }
        }

    # Pour linux_net et linux_desktop, on monte toujours /workspace en lecture/écriture
    workspace_dir = node_dir / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, content in node.files.items():
        # Évite la duplication /workspace/workspace/... si la clé commence déjà par workspace/
        normalized = rel_path[len("workspace/"):] if rel_path.startswith("workspace/") else rel_path
        if normalized:
            _safe_write_file(workspace_dir, normalized, content)
    return {
        str(workspace_dir.resolve()): {
            "bind": spec["workspace_path"],
            "mode": "rw",
        }
    }


class DockerOrchestrator:
    def __init__(self, client: Any | None = None, runtime_root: Path = RUNTIME_ROOT):
        self._injected_client = client
        self.runtime_root = runtime_root

    def _get_client(self) -> Any:
        if self._injected_client is not None:
            return self._injected_client
        try:
            client = docker.from_env()
            client.ping()
            return client
        except DockerException as exc:
            raise OrchestratorError(
                "Impossible de contacter le démon Docker. Vérifiez que Docker est démarré "
                "et que votre utilisateur a accès à /var/run/docker.sock.",
                status_code=503,
            ) from exc

    def _get_or_create_network(self, client: Any, infra_id: int) -> tuple[Any, ipaddress.IPv4Network | None]:
        net_name = network_name_for(infra_id)
        try:
            network = client.networks.get(net_name)
            return network, _extract_network_subnet(network)
        except NotFound:
            pass

        subnet = allocate_free_subnet(client)
        gateway = str(next(subnet.hosts()))
        ipam_pool = IPAMPool(subnet=str(subnet), gateway=gateway)
        ipam_config = IPAMConfig(pool_configs=[ipam_pool])

        try:
            network = client.networks.create(
                name=net_name,
                driver="bridge",
                ipam=ipam_config,
                labels={
                    MANAGED_LABEL: "true",
                    INFRA_ID_LABEL: str(infra_id),
                },
            )
        except APIError as exc:
            raise OrchestratorError(
                f"Échec de la création du réseau isolé '{net_name}' : {exc.explanation}",
                status_code=500,
            ) from exc

        return network, subnet

    def _ensure_image_available(self, client: Any, image_name: str) -> None:
        try:
            client.images.get(image_name)
        except ImageNotFound as exc:
            raise OrchestratorError(
                f"Image Docker vérifiée introuvable en local : '{image_name}'. "
                "Lancez './docker/build-images.sh' à la racine du projet pour préparer les images.",
                status_code=400,
            ) from exc

    def _remove_container_if_exists(self, client: Any, container_name: str) -> None:
        try:
            existing = client.containers.get(container_name)
            existing.remove(force=True)
        except NotFound:
            return

    def _start_single_node(
        self,
        client: Any,
        infra_id: int,
        network: Any,
        subnet: ipaddress.IPv4Network | None,
        node: NodeDefinition,
        used_ips: set[str],
    ) -> None:
        spec = MODULE_CATALOG.get(node.module_type)
        if spec is None:
            raise OrchestratorError(f"Type de module inconnu : '{node.module_type}'.")

        image_name = spec["docker_image"]
        self._ensure_image_available(client, image_name)

        cname = container_name_for(infra_id, node.id)
        try:
            existing = client.containers.get(cname)
            existing.reload()
            if existing.status == "running":
                ip = _extract_container_ip(existing, network.name)
                if ip:
                    used_ips.add(ip)
                return
            existing.remove(force=True)
        except NotFound:
            pass

        cfg = {**spec["default_config"], **(node.config or {})}
        env: dict[str, str] = {}
        if node.module_type == "postgres":
            env = {
                "POSTGRES_DB": str(cfg.get("db_name") or "app_db"),
                "POSTGRES_USER": str(cfg.get("db_user") or "postgres"),
                "POSTGRES_PASSWORD": str(cfg.get("db_password") or "password"),
            }
        elif node.module_type == "linux_desktop":
            env = {
                "PUID": "1000",
                "PGID": "1000",
                "TZ": "Europe/Paris",
            }

        volumes = _prepare_node_volumes(infra_id, node, spec, runtime_root=self.runtime_root)
        resolved_ip = resolve_node_ip(subnet, cfg.get("ip_address"), used_ips)
        if resolved_ip:
            used_ips.add(resolved_ip)

        endpoint_kwargs: dict[str, Any] = {"aliases": [node.id]}
        if resolved_ip:
            endpoint_kwargs["ipv4_address"] = resolved_ip
        networking_config = client.api.create_networking_config(
            {network.name: client.api.create_endpoint_config(**endpoint_kwargs)}
        )

        security_opt = (
            ["seccomp:unconfined"]
            if spec["seccomp_unconfined"]
            else ["no-new-privileges:true"]
        )

        create_kwargs: dict[str, Any] = {
            "image": image_name,
            "name": cname,
            "hostname": str(cfg.get("hostname") or node.id)[:63],
            "detach": True,
            "environment": env,
            "volumes": volumes,
            "network": network.name,
            "networking_config": networking_config,
            "mem_limit": spec["memory_limit"],
            "nano_cpus": int(spec["cpu_limit"] * 1_000_000_000),
            "pids_limit": spec["pids_limit"],
            "privileged": False,
            "security_opt": security_opt,
            "labels": {
                MANAGED_LABEL: "true",
                INFRA_ID_LABEL: str(infra_id),
                NODE_ID_LABEL: node.id,
                MODULE_TYPE_LABEL: node.module_type,
            },
        }
        if spec["cap_drop"]:
            create_kwargs["cap_drop"] = spec["cap_drop"]
        if spec["cap_add"]:
            create_kwargs["cap_add"] = spec["cap_add"]
        if spec["shm_size"]:
            create_kwargs["shm_size"] = spec["shm_size"]
        if spec["web_port"]:
            # Bind uniquement sur 127.0.0.1 avec port libre aléatoire (0) pour éviter tout conflit
            create_kwargs["ports"] = {f"{spec['web_port']}/tcp": ("127.0.0.1", 0)}

        try:
            container = client.containers.create(**create_kwargs)
            container.start()
        except APIError as exc:
            self._remove_container_if_exists(client, cname)
            raise OrchestratorError(
                f"Impossible de démarrer le module '{node.id}' ({node.module_type}) : {exc.explanation}",
                status_code=500,
            ) from exc

    def _collect_used_ips(self, client: Any, infra_id: int, net_name: str) -> set[str]:
        used: set[str] = set()
        containers = client.containers.list(
            all=True,
            filters={"label": [f"{MANAGED_LABEL}=true", f"{INFRA_ID_LABEL}={infra_id}"]},
        )
        for container in containers:
            ip = _extract_container_ip(container, net_name)
            if ip:
                used.add(ip)
        return used

    def start_infrastructure(
        self,
        infra_id: int,
        definition: InfrastructureDefinition,
    ) -> InfrastructureRuntimeStatus:
        """
        Crée le réseau isolé et démarre tous les modules qui ne sont pas « à la demande ».
        En cas d'échec, nettoie les conteneurs créés afin d'éviter un état partiel cassé.
        """
        if not definition.nodes:
            raise OrchestratorError("Impossible de démarrer une infrastructure vide (aucun module).")

        client = self._get_client()
        network, subnet = self._get_or_create_network(client, infra_id)
        used_ips = self._collect_used_ips(client, infra_id, network.name)

        try:
            for node in definition.nodes:
                spec = MODULE_CATALOG[node.module_type]
                if spec["on_demand"]:
                    # Les modules graphiques démarrent uniquement sur action dédiée
                    continue
                self._start_single_node(client, infra_id, network, subnet, node, used_ips)
        except OrchestratorError:
            self._cleanup_infra(client, infra_id)
            raise

        return self.get_infrastructure_status(infra_id, definition)

    def _cleanup_infra(self, client: Any, infra_id: int) -> None:
        containers = client.containers.list(
            all=True,
            filters={"label": [f"{MANAGED_LABEL}=true", f"{INFRA_ID_LABEL}={infra_id}"]},
        )
        for container in containers:
            try:
                container.remove(force=True)
            except APIError:
                pass

        net_name = network_name_for(infra_id)
        try:
            network = client.networks.get(net_name)
            network.remove()
        except (NotFound, APIError):
            pass

    def stop_infrastructure(
        self,
        infra_id: int,
        definition: InfrastructureDefinition,
    ) -> InfrastructureRuntimeStatus:
        """Arrête et supprime tous les conteneurs + le réseau isolé de l'infrastructure."""
        client = self._get_client()
        self._cleanup_infra(client, infra_id)
        return self.get_infrastructure_status(infra_id, definition)

    def start_node(
        self,
        infra_id: int,
        definition: InfrastructureDefinition,
        node_id: str,
    ) -> InfrastructureRuntimeStatus:
        """Démarre un module spécifique (notamment linux_desktop à la demande)."""
        node = next((n for n in definition.nodes if n.id == node_id), None)
        if node is None:
            raise OrchestratorError(f"Module '{node_id}' introuvable dans cette infrastructure.", status_code=404)

        client = self._get_client()
        net_name = network_name_for(infra_id)
        try:
            network = client.networks.get(net_name)
        except NotFound as exc:
            raise OrchestratorError(
                "Démarrez d'abord l'infrastructure avant de lancer un module individuel.",
                status_code=400,
            ) from exc

        subnet = _extract_network_subnet(network)
        used_ips = self._collect_used_ips(client, infra_id, network.name)
        self._start_single_node(client, infra_id, network, subnet, node, used_ips)
        return self.get_infrastructure_status(infra_id, definition)

    def stop_node(
        self,
        infra_id: int,
        definition: InfrastructureDefinition,
        node_id: str,
    ) -> InfrastructureRuntimeStatus:
        """Arrête et supprime un module individuel (ex. couper le bureau graphique pour libérer la RAM)."""
        node = next((n for n in definition.nodes if n.id == node_id), None)
        if node is None:
            raise OrchestratorError(f"Module '{node_id}' introuvable dans cette infrastructure.", status_code=404)

        client = self._get_client()
        self._remove_container_if_exists(client, container_name_for(infra_id, node_id))
        return self.get_infrastructure_status(infra_id, definition)

    def get_infrastructure_status(
        self,
        infra_id: int,
        definition: InfrastructureDefinition,
    ) -> InfrastructureRuntimeStatus:
        """Interroge Docker en temps réel pour connaître l'état, le réseau et l'IP de chaque module."""
        net_name = network_name_for(infra_id)
        try:
            client = self._get_client()
        except OrchestratorError:
            return InfrastructureRuntimeStatus(
                infra_id=infra_id,
                status="stopped",
                docker_available=False,
                network_name=net_name,
                subnet=None,
                nodes=[
                    NodeRuntimeStatus(
                        node_id=node.id,
                        name=node.name,
                        module_type=node.module_type,
                        on_demand=MODULE_CATALOG[node.module_type]["on_demand"],
                        state="stopped",
                        container_name=container_name_for(infra_id, node.id),
                    )
                    for node in definition.nodes
                ],
            )

        network_exists = False
        subnet_str: str | None = None
        try:
            network = client.networks.get(net_name)
            network_exists = True
            subnet = _extract_network_subnet(network)
            subnet_str = str(subnet) if subnet else None
        except NotFound:
            pass

        containers = client.containers.list(
            all=True,
            filters={"label": [f"{MANAGED_LABEL}=true", f"{INFRA_ID_LABEL}={infra_id}"]},
        )
        containers_by_node = {
            (c.labels or {}).get(NODE_ID_LABEL): c for c in containers
        }

        node_statuses: list[NodeRuntimeStatus] = []
        any_running = False
        for node in definition.nodes:
            spec = MODULE_CATALOG[node.module_type]
            container = containers_by_node.get(node.id)
            if container is None:
                node_statuses.append(
                    NodeRuntimeStatus(
                        node_id=node.id,
                        name=node.name,
                        module_type=node.module_type,
                        on_demand=spec["on_demand"],
                        state="stopped",
                        container_name=container_name_for(infra_id, node.id),
                    )
                )
            else:
                container.reload()
                c_state = container.status or "stopped"
                if c_state == "running":
                    any_running = True
                node_statuses.append(
                    NodeRuntimeStatus(
                        node_id=node.id,
                        name=node.name,
                        module_type=node.module_type,
                        on_demand=spec["on_demand"],
                        state=c_state,
                        ip_address=_extract_container_ip(container, net_name),
                        host_port=_extract_host_port(container, spec["web_port"]),
                        container_name=container.name,
                    )
                )

        overall_status = "running" if (network_exists or any_running) else "stopped"
        return InfrastructureRuntimeStatus(
            infra_id=infra_id,
            status=overall_status,
            docker_available=True,
            network_name=net_name if network_exists else None,
            subnet=subnet_str,
            nodes=node_statuses,
        )


orchestrator = DockerOrchestrator()
