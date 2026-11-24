"""
Catalogue des modules vérifiés (périmètre V1).

Seuls les types déclarés ici peuvent être utilisés dans une infrastructure
et orchestrés par Docker (liste blanche stricte + quotas RAM/CPU).
"""

from typing import Any

MODULE_CATALOG: dict[str, dict[str, Any]] = {
    "postgres": {
        "type": "postgres",
        "label": "Base de données PostgreSQL",
        "category": "leger",
        "category_label": "Léger",
        "description": "Base SQL prête à l'emploi (configuration du mot de passe, bases et tables).",
        "docker_image": "postgres:15-alpine",
        "memory_mb": 150,
        "memory_limit": "256m",
        "cpu_limit": 0.5,
        "on_demand": False,
        "workspace_path": "/docker-entrypoint-initdb.d",
        "default_config": {
            "db_name": "app_db",
            "db_user": "postgres",
            "db_password": "password",
            "ip_address": "",
        },
    },
    "linux_net": {
        "type": "linux_net",
        "label": "Poste Linux Réseau",
        "category": "reseau",
        "category_label": "Réseau",
        "description": "Poste Linux minimal équipé des outils réseau (iproute2, ping, curl, tcpdump).",
        "docker_image": "infra-web/linux-net:v1",
        "memory_mb": 200,
        "memory_limit": "256m",
        "cpu_limit": 0.5,
        "on_demand": False,
        "workspace_path": "/workspace",
        "default_config": {
            "hostname": "poste-linux",
            "ip_address": "",
            "gateway": "",
        },
    },
    "linux_desktop": {
        "type": "linux_desktop",
        "label": "Poste Linux Graphique",
        "category": "graphique",
        "category_label": "Graphique (à la demande)",
        "description": "Poste Linux avec bureau graphique accessible dans le navigateur (Wireshark, outils visuels).",
        "docker_image": "infra-web/linux-desktop:v1",
        "memory_mb": 800,
        "memory_limit": "1024m",
        "cpu_limit": 1.0,
        "on_demand": True,
        "workspace_path": "/workspace",
        "default_config": {
            "hostname": "poste-bureau",
            "ip_address": "",
            "gateway": "",
        },
    },
}


def get_catalog_list() -> list[dict[str, Any]]:
    """Retourne la liste des modules exposés au front-end."""
    return [
        {
            "type": item["type"],
            "label": item["label"],
            "category": item["category"],
            "category_label": item["category_label"],
            "description": item["description"],
            "memory_mb": item["memory_mb"],
            "on_demand": item["on_demand"],
            "workspace_path": item["workspace_path"],
            "default_config": item["default_config"],
        }
        for item in MODULE_CATALOG.values()
    ]


def is_valid_module_type(module_type: str) -> bool:
    return module_type in MODULE_CATALOG
