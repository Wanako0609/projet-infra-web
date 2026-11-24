# Projet Infra Web

Plateforme de déploiement d'infrastructures virtuelles en libre-service.

## Structure du Projet

```text
projet-infra-web/
├── .gitignore
├── README.md
├── docker-compose.yml
├── backend/
│   ├── requirements.txt
│   ├── main.py
│   └── app/
│       ├── api/
│       ├── core/
│       ├── models/
│       ├── schemas/
│       └── services/
└── frontend/
    ├── package.json
    ├── public/
    └── src/
```

## Démarrage rapide

### 1. Base de données (PostgreSQL)
```bash
docker-compose up -d
```

### 2. Back-end (FastAPI)
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```
L'API sera disponible sur `http://localhost:8000`.

### 3. Front-end
```bash
cd frontend
npm start
```
L'interface sera disponible sur `http://localhost:3000`.

*(Ou lancez l'ensemble des 3 services d'un coup avec `./dev.sh`.)*

## Modèle de persistance & d'export (V1)

Chaque module repose sur une **image Docker vérifiée du catalogue** (OS et outils préinstallés).  
Les éléments sauvegardés et exportés par infrastructure sont strictement déclaratifs :
- La topologie (`nodes` et `links`) et les paramètres structurés (`config` : nom de BDD, IP, hostname…).
- Les fichiers dédiés au module (`init.sql` pour PostgreSQL, dossier `/workspace` pour les postes Linux).

> **Limite assumée en V1** : les modifications système effectuées manuellement hors `/workspace` dans un conteneur (par exemple un `apt install` à la volée) ne sont pas incluses dans l'export. Tous les outils de base proviennent des images vérifiées du catalogue, et les fichiers/configurations de TP vivent dans `config` et `/workspace`.

