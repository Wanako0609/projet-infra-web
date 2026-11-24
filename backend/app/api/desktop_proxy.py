"""
Reverse-proxy HTTP et WebSocket authentifié vers le bureau graphique KasmVNC (linux_desktop).

Fonctionnement :
1. Le front obtient un token scopé via POST /api/infrastructures/{id}/nodes/{node_id}/desktop-session.
2. Le navigateur ouvre /api/desktop/{id}/{node_id}/?dt=<token>.
3. Ce proxy valide le token, dépose un cookie HttpOnly scopé au chemin /api/desktop/{id}/{node_id}/,
   puis redirige vers /api/desktop/{id}/{node_id}/ (sans token dans la barre d'adresse).
4. Toutes les sous-requêtes HTTP et le WebSocket KasmVNC (/websockify) envoient automatiquement
   ce cookie HttpOnly, et sont relayées vers 127.0.0.1:<host_port> (inaccessible de l'extérieur).
"""

import asyncio
import http.client
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import RedirectResponse
import websockets

from app.core.security import verify_desktop_token
from app.services.docker_orchestrator import OrchestratorError, orchestrator

router = APIRouter()

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "content-encoding",
}


def _cookie_name(infra_id: int, node_id: str) -> str:
    return f"infra_desktop_{infra_id}_{node_id}"


def _forward_http_sync(
    host_port: int,
    method: str,
    target_path: str,
    headers: dict[str, str],
    body: bytes,
) -> tuple[int, list[tuple[str, str]], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", host_port, timeout=15)
    try:
        conn.request(method, target_path, body=body or None, headers=headers)
        resp = conn.getresponse()
        resp_body = resp.read()
        resp_headers = resp.getheaders()
        return resp.status, resp_headers, resp_body
    finally:
        conn.close()


@router.get("/{infra_id}/{node_id}")
async def desktop_redirect_slash(infra_id: int, node_id: str, request: Request):
    """Assure la présence du slash final afin que les assets relatifs de KasmVNC résolvent correctement."""
    qs = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url=f"/api/desktop/{infra_id}/{node_id}/{qs}", status_code=status.HTTP_302_FOUND)


@router.api_route(
    "/{infra_id}/{node_id}/{subpath:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def desktop_http_proxy(infra_id: int, node_id: str, subpath: str, request: Request):
    cookie_key = _cookie_name(infra_id, node_id)
    dt = request.query_params.get("dt")

    # 1. Échange du paramètre ?dt= contre un cookie HttpOnly scopé à ce bureau
    if dt:
        verify_desktop_token(dt, infra_id, node_id)
        remaining_params = [(k, v) for k, v in request.query_params.multi_items() if k != "dt"]
        qs = f"?{urlencode(remaining_params)}" if remaining_params else ""
        redirect = RedirectResponse(
            url=f"/api/desktop/{infra_id}/{node_id}/{subpath}{qs}",
            status_code=status.HTTP_302_FOUND,
        )
        redirect.set_cookie(
            key=cookie_key,
            value=dt,
            httponly=True,
            samesite="lax",
            path=f"/api/desktop/{infra_id}/{node_id}/",
            max_age=7200,
        )
        return redirect

    # 2. Vérification du cookie HttpOnly sur toutes les requêtes suivantes
    token_cookie = request.cookies.get(cookie_key)
    if not token_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session bureau requise. Ouvrez le bureau depuis l'atelier visuel.",
        )
    verify_desktop_token(token_cookie, infra_id, node_id)

    try:
        host_port = orchestrator.get_desktop_host_port(infra_id, node_id)
    except OrchestratorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    # 3. Relai HTTP vers 127.0.0.1:<host_port>
    target_path = f"/{subpath}"
    if request.url.query:
        target_path = f"{target_path}?{request.url.query}"

    forward_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP_HEADERS and k.lower() != "cookie"
    }
    forward_headers["Host"] = f"127.0.0.1:{host_port}"
    forward_headers["Accept-Encoding"] = "identity"

    body = await request.body()
    try:
        status_code, resp_headers, resp_body = await asyncio.to_thread(
            _forward_http_sync,
            host_port,
            request.method,
            target_path,
            forward_headers,
            body,
        )
    except (OSError, http.client.HTTPException) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Le bureau graphique est en cours de démarrage, rafraîchissez dans 2 secondes.",
        ) from exc

    filtered_headers: dict[str, str] = {}
    for key, val in resp_headers:
        low = key.lower()
        if low in HOP_BY_HOP_HEADERS:
            continue
        if low == "location" and val.startswith("/"):
            val = f"/api/desktop/{infra_id}/{node_id}{val}"
        filtered_headers[key] = val

    return Response(content=resp_body, status_code=status_code, headers=filtered_headers)


@router.websocket("/{infra_id}/{node_id}/{subpath:path}")
async def desktop_ws_proxy(websocket: WebSocket, infra_id: int, node_id: str, subpath: str):
    """Relai WebSocket bidirectionnel (frames binaires + texte) pour le flux vidéo/clavier KasmVNC."""
    cookie_key = _cookie_name(infra_id, node_id)
    token = websocket.cookies.get(cookie_key) or websocket.query_params.get("dt")
    if not token:
        await websocket.close(code=4401, reason="Session bureau manquante")
        return

    try:
        verify_desktop_token(token, infra_id, node_id)
        host_port = orchestrator.get_desktop_host_port(infra_id, node_id)
    except (HTTPException, OrchestratorError):
        await websocket.close(code=4403, reason="Accès bureau refusé ou module arrêté")
        return

    requested_protocols = [
        p.strip()
        for p in (websocket.headers.get("sec-websocket-protocol") or "").split(",")
        if p.strip()
    ]

    qs = f"?{websocket.url.query}" if websocket.url.query else ""
    upstream_url = f"ws://127.0.0.1:{host_port}/{subpath}{qs}"

    try:
        upstream = await websockets.connect(
            upstream_url,
            subprotocols=requested_protocols or None,
            max_size=None,
            open_timeout=10,
        )
    except Exception:
        await websocket.close(code=1011, reason="Impossible de joindre KasmVNC")
        return

    accepted_subprotocol = getattr(upstream, "subprotocol", None)
    await websocket.accept(subprotocol=accepted_subprotocol)

    async def client_to_upstream() -> None:
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    await upstream.send(msg["bytes"])
                elif msg.get("text") is not None:
                    await upstream.send(msg["text"])
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    async def upstream_to_client() -> None:
        try:
            async for message in upstream:
                if isinstance(message, bytes):
                    await websocket.send_bytes(message)
                else:
                    await websocket.send_text(message)
        except Exception:
            pass

    t1 = asyncio.create_task(client_to_upstream())
    t2 = asyncio.create_task(upstream_to_client())
    try:
        _, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    finally:
        try:
            await upstream.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
