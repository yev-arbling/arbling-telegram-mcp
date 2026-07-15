"""Hosted HTTP transport: stateless streamable-HTTP MCP app with bearer auth.

Used by the `serve-http` CLI subcommand (Railway deployment). Security model:

- Fail closed: the server refuses to start without TELEGRAM_MCP_AUTH_TOKEN.
- Every path except GET /health requires `Authorization: Bearer <token>`,
  compared in constant time via hmac.compare_digest.
- Kill switch: a truthy TELEGRAM_MCP_DISABLED makes /health return 503 and
  the middleware reject all tool traffic with 503 (checked per request).
- /health returns booleans and the deploy SHA only — never account names,
  phone numbers, or group names.
"""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse

DEFAULT_PORT = 8080
HEALTH_PATH = "/health"
AUTH_TOKEN_ENV = "TELEGRAM_MCP_AUTH_TOKEN"
KILL_SWITCH_ENV = "TELEGRAM_MCP_DISABLED"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_disabled() -> bool:
    """Kill switch: truthy TELEGRAM_MCP_DISABLED disables all tool traffic."""
    return os.environ.get(KILL_SWITCH_ENV, "").strip().lower() in _TRUTHY


def _session_configured() -> bool:
    from .client import get_session_path, get_session_string

    if get_session_string():
        return True
    session_path = get_session_path()
    return Path(str(session_path) + ".session").exists() or session_path.exists()


def _groups_configured() -> bool:
    from .config import load_curated_groups

    try:
        config = load_curated_groups()
    except Exception:
        return False
    return any(groups for groups in config.values())


async def health(_request: Request) -> JSONResponse:
    """Health endpoint: no auth, booleans only — no account/group details."""
    disabled = is_disabled()
    payload = {
        "status": "disabled" if disabled else "ok",
        "sha": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "").strip() or "unknown",
        "session_configured": _session_configured(),
        "groups_configured": _groups_configured(),
    }
    return JSONResponse(payload, status_code=503 if disabled else 200)


async def _send_json(send, status: int, payload: dict, extra_headers=None) -> None:
    body = json.dumps(payload).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class BearerAuthMiddleware:
    """Pure ASGI middleware: bearer auth + kill switch on all paths except /health."""

    def __init__(self, app, token: str) -> None:
        if not token:
            raise RuntimeError("BearerAuthMiddleware requires a non-empty token")
        self._app = app
        self._expected = f"Bearer {token}".encode("utf-8")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path", "") == HEALTH_PATH:
            await self._app(scope, receive, send)
            return

        if is_disabled():
            await _send_json(
                send, 503, {"error": "Service disabled via TELEGRAM_MCP_DISABLED"}
            )
            return

        auth_header = b""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                auth_header = value
                break

        if not hmac.compare_digest(auth_header, self._expected):
            await _send_json(
                send,
                401,
                {"error": "Unauthorized"},
                extra_headers=[(b"www-authenticate", b"Bearer")],
            )
            return

        await self._app(scope, receive, send)


def build_http_app():
    """Build the ASGI app: stateless streamable-HTTP MCP + /health + bearer auth.

    Fails closed: raises RuntimeError when TELEGRAM_MCP_AUTH_TOKEN is missing
    or empty. The MCP endpoint is POST /mcp (FastMCP streamable_http_path).
    """
    token = os.environ.get(AUTH_TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError(
            f"{AUTH_TOKEN_ENV} is not set (or empty). The HTTP transport "
            "refuses to start without a bearer token. Set it to a strong "
            "random value (e.g. `openssl rand -hex 32`)."
        )

    from mcp.server.transport_security import TransportSecuritySettings

    from .server import create_mcp

    # DNS-rebinding protection (Host-header allowlist) is designed for
    # unauthenticated localhost servers. Hosted mode runs behind a public
    # Railway domain with mandatory bearer auth, so host validation would
    # only 421 legitimate clients — disable it; auth is the gate.
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
    mcp = create_mcp(
        stateless_http=True,
        json_response=True,
        transport_security=transport_security,
    )
    mcp.custom_route(HEALTH_PATH, methods=["GET"])(health)
    app = mcp.streamable_http_app()
    return BearerAuthMiddleware(app, token)


def run_http_server() -> None:
    """Run the hosted HTTP server on 0.0.0.0:$PORT (default 8080)."""
    import uvicorn

    app = build_http_app()
    port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    uvicorn.run(app, host="0.0.0.0", port=port)
