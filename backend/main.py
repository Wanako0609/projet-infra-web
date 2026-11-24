from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, infrastructures, modules, users
from app.models import infrastructure, user  # noqa: F401 - enregistre les tables dans Base.metadata
from app.services.db import Base, engine

# Crée automatiquement les tables manquantes dans PostgreSQL au démarrage
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Plateforme d'Infrastructures Virtuelles API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(modules.router, prefix="/api/modules", tags=["modules"])
app.include_router(infrastructures.router, prefix="/api/infrastructures", tags=["infrastructures"])


@app.get("/")
def read_root():
    return {"message": "Bienvenue sur l'API de la plateforme de déploiement d'infrastructures virtuelles"}
