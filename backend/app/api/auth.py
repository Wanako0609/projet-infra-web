from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.schemas.user import Token, UserCreate, UserOut
from app.models.user import User
from app.services.db import get_db
from app.core.security import get_password_hash, verify_password, create_access_token

router = APIRouter()

@router.post("/register", response_model=UserOut)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    """
    Crée un nouvel utilisateur en hachant son mot de passe.
    """
    # 1. Vérifier si l'email ou le pseudo existe déjà
    existing_user = db.query(User).filter(
        (User.email == user_in.email) | (User.username == user_in.username)
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=400, 
            detail="Cet email ou ce nom d'utilisateur est déjà pris."
        )
    
    # 2. Hacher le mot de passe
    hashed_password = get_password_hash(user_in.password)
    
    # 3. Insérer dans la base de données
    new_user = User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=hashed_password
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    Vérifie les identifiants et génère un token JWT.
    """
    # 1. Chercher l'utilisateur dans la base
    user = db.query(User).filter(User.username == form_data.username).first()
    
    # 2. Vérifier que l'utilisateur existe et que le mot de passe est bon
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants incorrects",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 3. Créer et renvoyer le token d'accès
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}