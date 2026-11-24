from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import bcrypt
import jwt

from app.core.config import settings
from app.models.user import User
from app.services.db import get_db

# Indique à FastAPI l'endpoint qui délivre le token OAuth2 (utilisé aussi par Swagger /docs)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode("utf-8")
    if len(password_bytes) > 72:
        return False
    return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe ne doit pas dépasser 72 octets.",
        )
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    now_utc = datetime.now(timezone.utc)
    if expires_delta:
        expire = now_utc + expires_delta
    else:
        expire = now_utc + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_user_from_token(token: str, db: Session) -> User:
    """
    Valide un token JWT d'accès et retourne l'utilisateur correspondant en base.
    Réutilisé par les routes HTTP (via get_current_user) et par les WebSockets.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Impossible de valider les identifiants",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("purpose") is not None:
            # Un token scopé (ex. bureau) ne peut pas servir de token d'accès général
            raise credentials_exception
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Le token a expiré",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte utilisateur désactivé",
        )

    return user


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    return decode_user_from_token(token, db)


def create_desktop_token(
    username: str,
    infra_id: int,
    node_id: str,
    expires_minutes: int = 120,
) -> str:
    """
    Crée un JWT scopé uniquement à l'accès proxy KasmVNC d'un module précis.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {
        "sub": username,
        "purpose": "desktop_proxy",
        "infra_id": infra_id,
        "node_id": node_id,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_desktop_token(token: str, expected_infra_id: int, expected_node_id: str) -> str:
    """
    Vérifie qu'un token de session bureau est valide et correspond bien à (infra_id, node_id).
    Retourne le username en cas de succès, ou lève 401.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session bureau invalide ou expirée.",
        ) from exc

    if (
        payload.get("purpose") != "desktop_proxy"
        or payload.get("infra_id") != expected_infra_id
        or payload.get("node_id") != expected_node_id
        or not payload.get("sub")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token de session non autorisé pour ce module.",
        )

    return str(payload["sub"])
