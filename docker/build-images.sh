#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "1/3 - Téléchargement de l'image vérifiée PostgreSQL (postgres:15-alpine)..."
docker pull postgres:15-alpine

echo "2/3 - Construction de l'image vérifiée Poste Linux Réseau (infra-web/linux-net:v1)..."
docker build -t infra-web/linux-net:v1 "$SCRIPT_DIR/linux-net"

if [[ "${1:-}" == "--no-desktop" ]]; then
    echo "3/3 - Image graphique ignorée (--no-desktop)."
else
    echo "3/3 - Construction de l'image vérifiée Poste Linux Graphique (infra-web/linux-desktop:v1)..."
    docker build -t infra-web/linux-desktop:v1 "$SCRIPT_DIR/linux-desktop"
fi

echo "✅ Images du catalogue prêtes !"
