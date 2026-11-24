from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Résolution absolue vers backend/.env pour que le chargement fonctionne
# quel que soit le dossier depuis lequel uvicorn est lancé
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "Infra Web API"
    SECRET_KEY: str = "secret-key-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    DATABASE_URL: str = "postgresql+psycopg://postgres:password@localhost:5432/infra_web_db"


settings = Settings()
