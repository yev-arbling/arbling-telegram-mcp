"""Tests for hosted HTTP mode: bearer auth, /health, kill switch, fail-closed start."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from arbling_telegram_mcp.http_server import build_http_app

from tests.conftest import VALID_YAML

TOKEN = "test-token-123"
MCP_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json, text/event-stream",
}
INITIALIZE_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
READ_ONLY_TOOLS = {
    "telegram_status",
    "list_my_groups",
    "list_curated_groups",
    "read_recent_messages",
    "search_messages",
    "get_message_thread",
    "refresh_session",
}


def _hosted_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    """Baseline hosted env: auth token set, no session, no groups."""
    env = {
        "TELEGRAM_MCP_AUTH_TOKEN": TOKEN,
        "TELEGRAM_SESSION_PATH": str(tmp_path / "no-session"),
        "TELEGRAM_CURATED_GROUPS_PATH": str(tmp_path / "no-groups.yaml"),
    }
    env.update(overrides)
    return env


@pytest.fixture()
def hosted_client(tmp_path: Path):
    """TestClient against a freshly built hosted app (lifespan running)."""
    with patch.dict(os.environ, _hosted_env(tmp_path)):
        os.environ.pop("TELEGRAM_MCP_DISABLED", None)
        os.environ.pop("TELEGRAM_SESSION_STRING", None)
        os.environ.pop("TELEGRAM_CURATED_GROUPS_B64", None)
        with TestClient(build_http_app()) as client:
            yield client


# ---------------------------------------------------------------------------
# Fail-closed startup
# ---------------------------------------------------------------------------


def test_missing_auth_token_refuses_to_start():
    with patch.dict(os.environ, {"TELEGRAM_MCP_AUTH_TOKEN": ""}):
        with pytest.raises(RuntimeError, match="TELEGRAM_MCP_AUTH_TOKEN"):
            build_http_app()


def test_whitespace_auth_token_refuses_to_start():
    with patch.dict(os.environ, {"TELEGRAM_MCP_AUTH_TOKEN": "   "}):
        with pytest.raises(RuntimeError, match="TELEGRAM_MCP_AUTH_TOKEN"):
            build_http_app()


# ---------------------------------------------------------------------------
# Bearer auth on the MCP path
# ---------------------------------------------------------------------------


def test_mcp_without_token_returns_401(hosted_client: TestClient):
    r = hosted_client.post("/mcp", json=INITIALIZE_BODY)
    assert r.status_code == 401
    assert r.json() == {"error": "Unauthorized"}
    assert r.headers.get("www-authenticate") == "Bearer"


def test_mcp_with_wrong_token_returns_401(hosted_client: TestClient):
    r = hosted_client.post(
        "/mcp",
        json=INITIALIZE_BODY,
        headers={
            "Authorization": "Bearer wrong-token",
            "Accept": "application/json, text/event-stream",
        },
    )
    assert r.status_code == 401


def test_mcp_with_malformed_auth_scheme_returns_401(hosted_client: TestClient):
    r = hosted_client.post(
        "/mcp", json=INITIALIZE_BODY, headers={"Authorization": TOKEN}
    )
    assert r.status_code == 401


def test_mcp_with_correct_token_passes_through(hosted_client: TestClient):
    r = hosted_client.post("/mcp", json=INITIALIZE_BODY, headers=MCP_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert data["result"]["serverInfo"]["name"] == "arbling-telegram-mcp"


def test_unknown_paths_also_require_auth(hosted_client: TestClient):
    # Fail closed: everything except /health is behind the token.
    r = hosted_client.get("/anything-else")
    assert r.status_code == 401


def test_exposed_tool_surface_is_exactly_the_read_only_set(hosted_client: TestClient):
    r = hosted_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers=MCP_HEADERS,
    )
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert names == READ_ONLY_TOOLS


# ---------------------------------------------------------------------------
# /health — reachable without auth, booleans only
# ---------------------------------------------------------------------------


def test_health_reachable_without_auth(hosted_client: TestClient):
    r = hosted_client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["sha"] == "unknown"
    assert data["session_configured"] is False
    assert data["groups_configured"] is False
    # Booleans and status/sha only — no account or group details.
    assert set(data) == {"status", "sha", "session_configured", "groups_configured"}


def test_health_reports_railway_sha(tmp_path: Path):
    env = _hosted_env(tmp_path, RAILWAY_GIT_COMMIT_SHA="abc1234")
    with patch.dict(os.environ, env):
        os.environ.pop("TELEGRAM_MCP_DISABLED", None)
        with TestClient(build_http_app()) as client:
            assert client.get("/health").json()["sha"] == "abc1234"


def test_health_session_configured_via_session_string(tmp_path: Path):
    env = _hosted_env(tmp_path, TELEGRAM_SESSION_STRING="1anything")
    with patch.dict(os.environ, env):
        os.environ.pop("TELEGRAM_MCP_DISABLED", None)
        with TestClient(build_http_app()) as client:
            data = client.get("/health").json()
    assert data["session_configured"] is True
    # The health payload must never contain the session string itself.
    assert "1anything" not in str(data)


def test_health_session_configured_via_session_file(
    tmp_path: Path, fake_session: Path
):
    env = _hosted_env(tmp_path, TELEGRAM_SESSION_PATH=str(fake_session))
    with patch.dict(os.environ, env):
        os.environ.pop("TELEGRAM_MCP_DISABLED", None)
        os.environ.pop("TELEGRAM_SESSION_STRING", None)
        with TestClient(build_http_app()) as client:
            assert client.get("/health").json()["session_configured"] is True


def test_health_groups_configured_via_b64(tmp_path: Path):
    b64 = base64.b64encode(VALID_YAML.encode("utf-8")).decode("ascii")
    env = _hosted_env(tmp_path, TELEGRAM_CURATED_GROUPS_B64=b64)
    with patch.dict(os.environ, env):
        os.environ.pop("TELEGRAM_MCP_DISABLED", None)
        with TestClient(build_http_app()) as client:
            data = client.get("/health").json()
    assert data["groups_configured"] is True
    # No group names in the health payload.
    assert "MCP Developers" not in str(data)


def test_health_groups_not_configured_when_b64_invalid(tmp_path: Path):
    env = _hosted_env(tmp_path, TELEGRAM_CURATED_GROUPS_B64="!!!not-base64!!!")
    with patch.dict(os.environ, env):
        os.environ.pop("TELEGRAM_MCP_DISABLED", None)
        with TestClient(build_http_app()) as client:
            assert client.get("/health").json()["groups_configured"] is False


# ---------------------------------------------------------------------------
# Kill switch — TELEGRAM_MCP_DISABLED
# ---------------------------------------------------------------------------


def test_kill_switch_health_returns_503_disabled(tmp_path: Path):
    env = _hosted_env(tmp_path, TELEGRAM_MCP_DISABLED="1")
    with patch.dict(os.environ, env):
        with TestClient(build_http_app()) as client:
            r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "disabled"


def test_kill_switch_rejects_tool_calls_even_with_valid_token(tmp_path: Path):
    env = _hosted_env(tmp_path, TELEGRAM_MCP_DISABLED="true")
    with patch.dict(os.environ, env):
        with TestClient(build_http_app()) as client:
            r = client.post("/mcp", json=INITIALIZE_BODY, headers=MCP_HEADERS)
    assert r.status_code == 503
    assert "error" in r.json()


def test_kill_switch_falsy_values_keep_service_enabled(tmp_path: Path):
    for value in ("", "0", "false", "off"):
        env = _hosted_env(tmp_path, TELEGRAM_MCP_DISABLED=value)
        with patch.dict(os.environ, env):
            with TestClient(build_http_app()) as client:
                assert client.get("/health").status_code == 200
