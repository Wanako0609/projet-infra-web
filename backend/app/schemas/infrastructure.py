from datetime import datetime
from pathlib import PurePosixPath
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.catalog import is_valid_module_type

SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$")
MAX_FILE_CONTENT_BYTES = 100_000  # 100 Ko par fichier de config embarqué


class ModuleCatalogOut(BaseModel):
    type: str
    label: str
    category: str
    category_label: str
    description: str
    memory_mb: int
    on_demand: bool
    workspace_path: str
    default_config: dict[str, Any]


class NodeDefinition(BaseModel):
    id: str = Field(..., description="Identifiant technique unique du module (ex: db-1, pc-1)")
    module_type: str = Field(..., description="Type issu du catalogue vérifié")
    name: str = Field(..., min_length=1, max_length=80)
    x: float = 0.0
    y: float = 0.0
    config: dict[str, Any] = Field(default_factory=dict)
    # Petits fichiers de config / workspace associés au module (ex: init.sql, workspace/consigne.txt)
    files: dict[str, str] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def validate_node_id(cls, value: str) -> str:
        if not SAFE_ID_PATTERN.match(value):
            raise ValueError(
                "L'identifiant d'un module doit commencer par un caractère alphanumérique "
                "et ne contenir que lettres, chiffres, '-' ou '_' (max 63 caractères)."
            )
        return value

    @field_validator("module_type")
    @classmethod
    def validate_module_type(cls, value: str) -> str:
        if not is_valid_module_type(value):
            raise ValueError(f"Type de module non autorisé dans le catalogue : '{value}'.")
        return value

    @field_validator("files")
    @classmethod
    def validate_files(cls, files: dict[str, str]) -> dict[str, str]:
        for rel_path, content in files.items():
            if not rel_path or rel_path.startswith("/") or "\\" in rel_path or "\x00" in rel_path:
                raise ValueError(f"Chemin de fichier invalide : '{rel_path}'.")
            parts = PurePosixPath(rel_path).parts
            if any(part in ("", ".", "..") for part in parts):
                raise ValueError(f"Chemin de fichier interdit (path traversal) : '{rel_path}'.")
            if len(content.encode("utf-8")) > MAX_FILE_CONTENT_BYTES:
                raise ValueError(
                    f"Le fichier '{rel_path}' dépasse la taille maximale autorisée ({MAX_FILE_CONTENT_BYTES} octets)."
                )
        return files


class LinkDefinition(BaseModel):
    id: str
    source: str
    target: str

    @field_validator("id")
    @classmethod
    def validate_link_id(cls, value: str) -> str:
        if not SAFE_ID_PATTERN.match(value):
            raise ValueError("Identifiant de lien invalide.")
        return value


class InfrastructureDefinition(BaseModel):
    schema_version: str = "1.0"
    nodes: list[NodeDefinition] = Field(default_factory=list)
    links: list[LinkDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph_integrity(self) -> "InfrastructureDefinition":
        node_ids: set[str] = set()
        for node in self.nodes:
            if node.id in node_ids:
                raise ValueError(f"Identifiant de module dupliqué : '{node.id}'.")
            node_ids.add(node.id)

        link_ids: set[str] = set()
        for link in self.links:
            if link.id in link_ids:
                raise ValueError(f"Identifiant de lien dupliqué : '{link.id}'.")
            link_ids.add(link.id)
            if link.source == link.target:
                raise ValueError(f"Le lien '{link.id}' ne peut pas relier un module à lui-même.")
            if link.source not in node_ids or link.target not in node_ids:
                raise ValueError(
                    f"Le lien '{link.id}' référence un module inexistant ({link.source} -> {link.target})."
                )
        return self


class InfrastructureCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    definition: InfrastructureDefinition = Field(default_factory=InfrastructureDefinition)


class InfrastructureUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    definition: InfrastructureDefinition | None = None


class ShareCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)


class ShareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    username: str
    email: str
    permission: Literal["read_only"] = "read_only"
    created_at: datetime


class InfrastructureOut(BaseModel):
    id: int
    name: str
    description: str
    owner_id: int
    owner_username: str
    status: str
    access_level: Literal["owner", "read_only"]
    definition: InfrastructureDefinition
    shares: list[ShareOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class InfrastructureListOut(BaseModel):
    owned: list[InfrastructureOut]
    shared: list[InfrastructureOut]
