"""
Routes d'accès interactif aux modules par double-clic (Étape 5) :
- Console SQL PostgreSQL (tables + exécution de requêtes via docker exec psql)
- Terminal web interactif (WebSocket FastAPI <-> PTY Docker)
- Création de session bureau authentifiée pour le proxy KasmVNC (linux_desktop)
"""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.infrastructures import _assert_is_owner, _get_infra_or_404
from app.core.security import create_desktop_token, decode_user_from_token, get_current_user
from app.models.user import User
from app.schemas.infrastructure import InfrastructureDefinition
from app.services.db import SessionLocal, get_db
from app.services.docker_orchestrator import OrchestratorError, orchestrator

router = APIRouter()


class SqlQueryIn(BaseModel):
    query: str = Field(..., min_length=1, max_length=20_000)


class SqlQueryOut(BaseModel):
    exit_code: int
    stdout: str
    stderr: str


class SqlTablesOut(BaseModel):
    tables: list[str]


class DesktopSessionOut(BaseModel):
    url: str
    host_port: int
    started_on_demand: bool


@router.get("/{infra_id}/nodes/{node_id}/sql/tables", response_model=SqlTablesOut)
def get_sql_tables(
    infra_id: int,
    node_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Liste les tables du schéma public d'un module PostgreSQL (propriétaire uniquement)."""
    infra = _get_infra_or_404(db, infra_id)
    _assert_is_owner(infra, current_user)
    definition = InfrastructureDefinition.model_validate(infra.definition or {})
    try:
        tables = orchestrator.list_sql_tables(infra.id, definition, node_id)
    except OrchestratorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return SqlTablesOut(tables=tables)


@router.post("/{infra_id}/nodes/{node_id}/sql", response_model=SqlQueryOut)
def execute_sql_query(
    infra_id: int,
    node_id: str,
    payload: SqlQueryIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Exécute une requête SQL dans un module PostgreSQL démarré (propriétaire uniquement)."""
    infra = _get_infra_or_404(db, infra_id)
    _assert_is_owner(infra, current_user)
    definition = InfrastructureDefinition.model_validate(infra.definition or {})
    try:
        result = orchestrator.exec_sql(infra.id, definition, node_id, payload.query)
    except OrchestratorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return SqlQueryOut(**result)


@router.post("/{infra_id}/nodes/{node_id}/desktop-session", response_model=DesktopSessionOut)
def create_desktop_session(
    infra_id: int,
    node_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Prépare l'accès authentifié au bureau graphique (KasmVNC / Wireshark).
    Démarre automatiquement le module à la demande s'il est encore arrêté (et que l'infra tourne).
    """
    infra = _get_infra_or_404(db, infra_id)
    _assert_is_owner(infra, current_user)
    definition = InfrastructureDefinition.model_validate(infra.definition or {})

    node = next((n for n in definition.nodes if n.id == node_id), None)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Module '{node_id}' introuvable.")
    if node.module_type != "linux_desktop":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce module ne dispose pas de bureau graphique.",
        )

    started_on_demand = False
    try:
        host_port = orchestrator.get_desktop_host_port(infra.id, node_id)
    except OrchestratorError:
        # Démarre automatiquement le poste graphique à la demande
        try:
            runtime = orchestrator.start_node(infra.id, definition, node_id)
            infra.status = runtime.status
            db.commit()
            host_port = orchestrator.get_desktop_host_port(infra.id, node_id)
            started_on_demand = True
        except OrchestratorError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    desktop_token = create_desktop_token(current_user.username, infra.id, node_id)
    base_url = str(request.base_url).rstrip("/")
    proxy_url = f"{base_url}/api/desktop/{infra.id}/{node_id}/?dt={desktop_token}"
    return DesktopSessionOut(
        url=proxy_url,
        host_port=host_port,
        started_on_demand=started_on_demand,
    )


@router.websocket("/{infra_id}/nodes/{node_id}/terminal")
async def terminal_websocket(
    websocket: WebSocket,
    infra_id: int,
    node_id: str,
    token: str = Query(..., description="Token JWT de l'utilisateur connecté"),
):
    """
    Pont WebSocket temps réel entre xterm.js (navigateur) et un shell PTY dans le conteneur Linux.
    Réservé au propriétaire de l'infrastructure.
    """
    db = SessionLocal()
    try:
        try:
            current_user = decode_user_from_token(token, db)
            infra = _get_infra_or_404(db, infra_id)
            _assert_is_owner(infra, current_user)
            definition = InfrastructureDefinition.model_validate(infra.definition or {})
        except HTTPException as exc:
            await websocket.close(code=4403 if exc.status_code == 403 else 4401, reason=exc.detail)
            return
    finally:
        db.close()

    try:
        client, exec_id, docker_sock = orchestrator.open_terminal_exec(infra_id, definition, node_id)
    except OrchestratorError as exc:
        await websocket.close(code=4400, reason=str(exc))
        return

    await websocket.accept()
    raw_sock = getattr(docker_sock, "_sock", docker_sock)
    closed = asyncio.Event()

    async def pty_to_ws() -> None:
        try:
            while not closed.is_set():
                data = await asyncio.to_thread(raw_sock.recv, 4096)
                if not data:
                    break
                await websocket.send_text(data.decode("utf-8", errors="replace"))
        except Exception:
            pass
        finally:
            closed.set()

    async def ws_to_pty() -> None:
        try:
            while not closed.is_set():
                msg = await websocket.receive_text()
                # Protocole léger : les messages de redimensionnement sont préfixés par \x00RESIZE:
                if msg.startswith("\x00RESIZE:"):
                    try:
                        dims = json.loads(msg[len("\x00RESIZE:"):])
                        rows = max(5, min(200, int(dims.get("rows", 24))))
                        cols = max(20, min(400, int(dims.get("cols", 80))))
                        await asyncio.to_thread(client.api.exec_resize, exec_id, height=rows, width=cols)
                    except Exception:
                        pass
                else:
                    await asyncio.to_thread(raw_sock.sendall, msg.encode("utf-8"))
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            closed.set()

    reader_task = asyncio.create_task(pty_to_ws())
    writer_task = asyncio.create_task(ws_to_pty())
    try:
        done, pending = await asyncio.wait(
            {reader_task, writer_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        closed.set()
        for task in pending:
            task.cancel()
    finally:
        try:
            raw_sock.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
