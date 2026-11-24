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
Vous pouvez ouvrir `frontend/public/index.html` directement dans un navigateur ou utiliser un serveur statique local.
