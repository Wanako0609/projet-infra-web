from fastapi import APIRouter, Depends

from app.core.catalog import get_catalog_list
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.infrastructure import ModuleCatalogOut

router = APIRouter()


@router.get("", response_model=list[ModuleCatalogOut])
def list_modules(current_user: User = Depends(get_current_user)):
    """
    Retourne le catalogue des modules vérifiés autorisés sur la plateforme.
    """
    return get_catalog_list()
