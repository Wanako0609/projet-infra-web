from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session, joinedload

from app.core.security import get_current_user
from app.models.infrastructure import Infrastructure, InfrastructureShare
from app.models.user import User
from app.schemas.infrastructure import (
    InfrastructureCreate,
    InfrastructureDefinition,
    InfrastructureListOut,
    InfrastructureOut,
    InfrastructureRuntimeStatus,
    InfrastructureUpdate,
    ShareCreate,
    ShareOut,
)
from app.services.db import get_db
from app.services.docker_orchestrator import OrchestratorError, orchestrator
from app.services.infra_archive import (
    ArchiveError,
    MAX_ZIP_UPLOAD_BYTES,
    build_infra_zip,
    parse_infra_zip,
)

router = APIRouter()


def _serialize_share(share: InfrastructureShare) -> ShareOut:
    return ShareOut(
        id=share.id,
        user_id=share.user_id,
        username=share.user.username,
        email=share.user.email,
        permission="read_only",
        created_at=share.created_at,
    )


def _serialize_infrastructure(
    infra: Infrastructure,
    current_user: User,
) -> InfrastructureOut:
    is_owner = infra.owner_id == current_user.id
    raw_definition = infra.definition or {}
    definition = InfrastructureDefinition.model_validate(raw_definition)

    # Seul le propriétaire voit la liste complète des partages de son infrastructure
    shares = [_serialize_share(s) for s in infra.shares] if is_owner else []

    return InfrastructureOut(
        id=infra.id,
        name=infra.name,
        description=infra.description,
        owner_id=infra.owner_id,
        owner_username=infra.owner.username,
        status=infra.status,
        access_level="owner" if is_owner else "read_only",
        definition=definition,
        shares=shares,
        created_at=infra.created_at,
        updated_at=infra.updated_at,
    )


def _get_infra_or_404(db: Session, infra_id: int) -> Infrastructure:
    infra = (
        db.query(Infrastructure)
        .options(
            joinedload(Infrastructure.owner),
            joinedload(Infrastructure.shares).joinedload(InfrastructureShare.user),
        )
        .filter(Infrastructure.id == infra_id)
        .first()
    )
    if infra is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Infrastructure introuvable.",
        )
    return infra


def _assert_can_read(infra: Infrastructure, current_user: User) -> None:
    if infra.owner_id == current_user.id:
        return
    if any(share.user_id == current_user.id for share in infra.shares):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Vous n'avez pas accès à cette infrastructure.",
    )


def _assert_is_owner(infra: Infrastructure, current_user: User) -> None:
    if infra.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Action réservée au propriétaire (accès en lecture seule).",
        )


@router.get("", response_model=InfrastructureListOut)
def list_infrastructures(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Liste les infrastructures dans deux espaces distincts :
    - owned  : Mes infrastructures (lecture / écriture / partage)
    - shared : Partagées avec moi (lecture seule)
    """
    owned_rows = (
        db.query(Infrastructure)
        .options(
            joinedload(Infrastructure.owner),
            joinedload(Infrastructure.shares).joinedload(InfrastructureShare.user),
        )
        .filter(Infrastructure.owner_id == current_user.id)
        .order_by(Infrastructure.updated_at.desc())
        .all()
    )

    shared_rows = (
        db.query(Infrastructure)
        .join(InfrastructureShare, InfrastructureShare.infrastructure_id == Infrastructure.id)
        .options(joinedload(Infrastructure.owner))
        .filter(InfrastructureShare.user_id == current_user.id)
        .order_by(Infrastructure.updated_at.desc())
        .all()
    )

    return InfrastructureListOut(
        owned=[_serialize_infrastructure(infra, current_user) for infra in owned_rows],
        shared=[_serialize_infrastructure(infra, current_user) for infra in shared_rows],
    )


@router.post("", response_model=InfrastructureOut, status_code=status.HTTP_201_CREATED)
def create_infrastructure(
    payload: InfrastructureCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Crée une nouvelle infrastructure appartenant à l'utilisateur connecté.
    """
    infra = Infrastructure(
        name=payload.name.strip(),
        description=payload.description.strip(),
        owner_id=current_user.id,
        definition=payload.definition.model_dump(),
        status="stopped",
    )
    db.add(infra)
    db.commit()
    db.refresh(infra)
    # Recharge avec les relations (owner, shares)
    infra = _get_infra_or_404(db, infra.id)
    return _serialize_infrastructure(infra, current_user)


@router.post("/import", response_model=InfrastructureOut, status_code=status.HTTP_201_CREATED)
async def import_infrastructure(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Importe une infrastructure depuis une archive .zip déclarative (infra.json + configs/)
    et la crée dans l'espace personnel de l'utilisateur connecté.
    """
    # Lecture plafonnée pour rejeter rapidement un upload trop gros
    raw_bytes = await file.read(MAX_ZIP_UPLOAD_BYTES + 1)
    try:
        manifest = parse_infra_zip(raw_bytes)
    except ArchiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    infra_name = name.strip() if name and name.strip() else manifest.name
    if len(infra_name) > 120:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le nom de l'infrastructure ne doit pas dépasser 120 caractères.",
        )

    infra = Infrastructure(
        name=infra_name,
        description=manifest.description,
        owner_id=current_user.id,
        definition=manifest.definition.model_dump(),
        status="stopped",
    )
    db.add(infra)
    db.commit()
    db.refresh(infra)
    infra = _get_infra_or_404(db, infra.id)
    return _serialize_infrastructure(infra, current_user)


@router.get("/{infra_id}/export")
def export_infrastructure(
    infra_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Exporte une infrastructure sous forme d'archive .zip déclarative.
    Accessible au propriétaire ainsi qu'aux utilisateurs ayant un accès lecture seule.
    """
    infra = _get_infra_or_404(db, infra_id)
    _assert_can_read(infra, current_user)

    definition = InfrastructureDefinition.model_validate(infra.definition or {})
    zip_bytes, filename = build_infra_zip(infra.name, infra.description, definition)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{infra_id}", response_model=InfrastructureOut)
def get_infrastructure(
    infra_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Consulte le détail d'une infrastructure (propriétaire ou invité en lecture seule).
    """
    infra = _get_infra_or_404(db, infra_id)
    _assert_can_read(infra, current_user)
    return _serialize_infrastructure(infra, current_user)


@router.put("/{infra_id}", response_model=InfrastructureOut)
def update_infrastructure(
    infra_id: int,
    payload: InfrastructureUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Modifie le nom, la description ou la topologie (propriétaire uniquement).
    """
    infra = _get_infra_or_404(db, infra_id)
    _assert_is_owner(infra, current_user)

    if payload.name is not None:
        infra.name = payload.name.strip()
    if payload.description is not None:
        infra.description = payload.description.strip()
    if payload.definition is not None:
        infra.definition = payload.definition.model_dump()

    db.commit()
    infra = _get_infra_or_404(db, infra_id)
    return _serialize_infrastructure(infra, current_user)


@router.delete("/{infra_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_infrastructure(
    infra_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Supprime une infrastructure, ses conteneurs Docker éventuels et ses partages (propriétaire uniquement).
    """
    infra = _get_infra_or_404(db, infra_id)
    _assert_is_owner(infra, current_user)

    # Nettoyage Docker best-effort pour ne pas laisser de conteneurs orphelins
    try:
        definition = InfrastructureDefinition.model_validate(infra.definition or {})
        orchestrator.stop_infrastructure(infra.id, definition)
    except OrchestratorError:
        pass

    db.delete(infra)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{infra_id}/start", response_model=InfrastructureRuntimeStatus)
def start_infrastructure(
    infra_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Déploie l'infrastructure sur Docker (réseau isolé + modules non 'à la demande').
    Réservé au propriétaire.
    """
    infra = _get_infra_or_404(db, infra_id)
    _assert_is_owner(infra, current_user)

    definition = InfrastructureDefinition.model_validate(infra.definition or {})
    try:
        runtime = orchestrator.start_infrastructure(infra.id, definition)
    except OrchestratorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    infra.status = runtime.status
    db.commit()
    return runtime


@router.post("/{infra_id}/stop", response_model=InfrastructureRuntimeStatus)
def stop_infrastructure(
    infra_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Arrête et nettoie tous les conteneurs et le réseau isolé de l'infrastructure.
    Réservé au propriétaire.
    """
    infra = _get_infra_or_404(db, infra_id)
    _assert_is_owner(infra, current_user)

    definition = InfrastructureDefinition.model_validate(infra.definition or {})
    try:
        runtime = orchestrator.stop_infrastructure(infra.id, definition)
    except OrchestratorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    infra.status = runtime.status
    db.commit()
    return runtime


@router.get("/{infra_id}/status", response_model=InfrastructureRuntimeStatus)
def get_infrastructure_status(
    infra_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retourne l'état temps réel des conteneurs et du réseau Docker.
    Accessible au propriétaire ainsi qu'aux utilisateurs en lecture seule.
    """
    infra = _get_infra_or_404(db, infra_id)
    _assert_can_read(infra, current_user)

    definition = InfrastructureDefinition.model_validate(infra.definition or {})
    runtime = orchestrator.get_infrastructure_status(infra.id, definition)
    if runtime.docker_available and infra.status != runtime.status:
        infra.status = runtime.status
        db.commit()
    return runtime


@router.post("/{infra_id}/nodes/{node_id}/start", response_model=InfrastructureRuntimeStatus)
def start_infrastructure_node(
    infra_id: int,
    node_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Démarre un module spécifique (utile pour les postes graphiques à la demande).
    Réservé au propriétaire.
    """
    infra = _get_infra_or_404(db, infra_id)
    _assert_is_owner(infra, current_user)

    definition = InfrastructureDefinition.model_validate(infra.definition or {})
    try:
        runtime = orchestrator.start_node(infra.id, definition, node_id)
    except OrchestratorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    infra.status = runtime.status
    db.commit()
    return runtime


@router.post("/{infra_id}/nodes/{node_id}/stop", response_model=InfrastructureRuntimeStatus)
def stop_infrastructure_node(
    infra_id: int,
    node_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Arrête un module spécifique (ex. couper le poste graphique pour libérer la RAM).
    Réservé au propriétaire.
    """
    infra = _get_infra_or_404(db, infra_id)
    _assert_is_owner(infra, current_user)

    definition = InfrastructureDefinition.model_validate(infra.definition or {})
    try:
        runtime = orchestrator.stop_node(infra.id, definition, node_id)
    except OrchestratorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    infra.status = runtime.status
    db.commit()
    return runtime


@router.post("/{infra_id}/shares", response_model=ShareOut, status_code=status.HTTP_201_CREATED)
def share_infrastructure(
    infra_id: int,
    payload: ShareCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Partage une infrastructure en lecture seule avec un autre utilisateur (propriétaire uniquement).
    """
    infra = _get_infra_or_404(db, infra_id)
    _assert_is_owner(infra, current_user)

    target_user = db.query(User).filter(User.username == payload.username.strip()).first()
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Utilisateur '{payload.username}' introuvable.",
        )
    if target_user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vous êtes déjà propriétaire de cette infrastructure.",
        )

    existing_share = (
        db.query(InfrastructureShare)
        .filter(
            InfrastructureShare.infrastructure_id == infra.id,
            InfrastructureShare.user_id == target_user.id,
        )
        .first()
    )
    if existing_share is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cette infrastructure est déjà partagée avec '{target_user.username}'.",
        )

    share = InfrastructureShare(
        infrastructure_id=infra.id,
        user_id=target_user.id,
        permission="read_only",
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    share.user = target_user
    return _serialize_share(share)


@router.delete("/{infra_id}/shares/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share(
    infra_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Révoque le partage d'une infrastructure pour un utilisateur donné (propriétaire uniquement).
    """
    infra = _get_infra_or_404(db, infra_id)
    _assert_is_owner(infra, current_user)

    share = (
        db.query(InfrastructureShare)
        .filter(
            InfrastructureShare.infrastructure_id == infra.id,
            InfrastructureShare.user_id == user_id,
        )
        .first()
    )
    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partage introuvable.",
        )

    db.delete(share)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
