from fastapi import APIRouter, Depends
from app.schemas.user import UserOut
from app.models.user import User
from app.core.security import get_current_user

router = APIRouter()

@router.get("/me", response_model=UserOut)
def read_users_me(current_user: User = Depends(get_current_user)):
    """
    Returns the profile data of the currently logged-in user.
    """
    # current_user is automatically provided by the get_current_user dependency
    return current_user