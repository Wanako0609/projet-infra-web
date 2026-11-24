from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth, users
from app.services.db import engine, Base
from app.models import user

# Cette ligne ordonne la création de toutes les tables manquantes
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Plateforme d'Infrastructures Virtuelles API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])

@app.get("/")
def read_root():
    return {"message": "Bienvenue sur l'API de la plateforme de déploiement d'infrastructures virtuelles"}
