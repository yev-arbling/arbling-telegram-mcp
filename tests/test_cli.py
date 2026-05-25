"""Tests for CLI subcommands: list-groups and status output shapes."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from tests.conftest import AsyncIter, _make_mock_dialog


# ---------------------------------------------------------------------------
# list-groups — output is valid YAML with required categories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_groups_outputs_yaml_structure(
    mock_telethon, fake_config: Path, capsys
):
    channel = _make_mock_dialog(-1001111111111, "Test Channel", entity_type="channel", participant_count=500)
    group = _make_mock_dialog(-1002222222222, "Test Group", entity_type="chat", participant_count=30)

    mock_telethon.iter_dialogs.return_value = AsyncIter([channel, group])

    from arbling_telegram_mcp.cli import _cmd_list_groups

    with patch.dict(
        "os.environ",
        {
            "TELEGRAM_API_ID": "12345",
            "TELEGRAM_API_HASH": "abcdef",
            "TELEGRAM_CURATED_GROUPS_PATH": str(fake_config),
        },
    ):
        await _cmd_list_groups()

    captured = capsys.readouterr()
    output = captured.out

    # Must contain required skeleton categories
    assert "tech_news: []" in output
    assert "investor: []" in output
    assert "tech_mentors: []" in output

    # Must contain the discovered groups as comments
    assert "-1001111111111" in output
    assert "Test Channel" in output
    assert "-1002222222222" in output
    assert "Test Group" in output


@pytest.mark.asyncio
async def test_list_groups_skeleton_is_parseable_yaml(
    mock_telethon, fake_config: Path, capsys
):
    mock_telethon.iter_dialogs.return_value = AsyncIter([])

    from arbling_telegram_mcp.cli import _cmd_list_groups

    with patch.dict(
        "os.environ",
        {"TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "abcdef"},
    ):
        await _cmd_list_groups()

    captured = capsys.readouterr()
    lines = [
        line for line in captured.out.splitlines() if not line.strip().startswith("#")
    ]
    parseable = "\n".join(lines)
    parsed = yaml.safe_load(parseable)
    assert parsed is not None
    assert "tech_news" in parsed
    assert "investor" in parsed
    assert "tech_mentors" in parsed


# ---------------------------------------------------------------------------
# status — output is valid JSON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_outputs_valid_json(capsys):
    status_payload = {
        "connected": True,
        "account_name": "Test User",
        "account_phone_masked": "+971*****56",
        "session_age_days": 1.2,
        "curated_group_count_by_category": {"tech_news": 2},
    }

    with patch(
        "arbling_telegram_mcp.cli._cmd_status",
        new_callable=lambda: lambda: type(
            "M", (), {"__call__": staticmethod(lambda: None)}
        )(),
    ):
        pass  # just verify the import doesn't blow up

    # Test directly: call get_telegram_status mock and capture output
    with patch(
        "arbling_telegram_mcp.client.get_telegram_status",
        new_callable=AsyncMock,
        return_value=status_payload,
    ):
        from arbling_telegram_mcp.cli import _cmd_status

        await _cmd_status()

    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["connected"] is True
    assert parsed["account_name"] == "Test User"


# ---------------------------------------------------------------------------
# auth — already authenticated path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_already_authenticated(mock_telethon, fake_config: Path, capsys):
    from arbling_telegram_mcp.cli import _cmd_auth

    with patch.dict(
        "os.environ",
        {"TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "abcdef"},
    ):
        await _cmd_auth()

    captured = capsys.readouterr()
    assert "Already authenticated" in captured.out or "Test" in captured.out


# ---------------------------------------------------------------------------
# Path safety — TELEGRAM_CURATED_GROUPS_PATH is honored
# ---------------------------------------------------------------------------


def test_config_path_from_env(tmp_path: Path):
    from arbling_telegram_mcp.config import get_config_path

    custom = str(tmp_path / "my-groups.yaml")
    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_PATH": custom}):
        path = get_config_path()
    assert path == tmp_path / "my-groups.yaml"
