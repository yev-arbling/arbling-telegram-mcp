"""Shared fixtures: fake session file, fake YAML config, mock TelegramClient."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


VALID_YAML = """\
tech_news:
  - id: -1001234567890
    name: "MCP Developers"
  - id: -1002345678901
    name: "Indie Hackers UAE"

investor:
  - id: -1009876543210
    name: "Pre-seed Underground"

tech_mentors:
  - id: -1003333333333
    name: "AI Native Founders"
"""


@pytest.fixture()
def fake_session(tmp_path: Path) -> Path:
    """Create a fake .session file; return path without the .session extension."""
    session_file = tmp_path / "session.session"
    session_file.write_bytes(b"fake telethon session data")
    return tmp_path / "session"


@pytest.fixture()
def fake_config(tmp_path: Path) -> Path:
    """Write a valid curated-groups.yaml and return its Path."""
    config_file = tmp_path / "curated-groups.yaml"
    config_file.write_text(VALID_YAML, encoding="utf-8")
    return config_file


class AsyncIter:
    """Utility: wraps a list as an async iterator for mocking iter_dialogs/iter_messages."""

    def __init__(self, items: list):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


def _make_mock_dialog(
    dialog_id: int,
    name: str,
    entity_type: str = "channel",
    participant_count: int = 100,
) -> MagicMock:
    """Return a MagicMock shaped like a Telethon Dialog."""
    from telethon.tl.types import Channel, Chat, User

    dialog = MagicMock()
    dialog.id = dialog_id
    dialog.name = name

    if entity_type == "user":
        entity = MagicMock(spec=User)
    elif entity_type == "chat":
        entity = MagicMock(spec=Chat)
        entity.participants_count = participant_count
    else:
        entity = MagicMock(spec=Channel)
        entity.participants_count = participant_count
        entity.megagroup = entity_type == "supergroup"

    dialog.entity = entity
    dialog.message = MagicMock()
    dialog.message.date = None
    return dialog


def _make_mock_message(
    msg_id: int = 1,
    text: str = "Hello world",
    has_media: bool = False,
    group_id: int = -1001234567890,
) -> MagicMock:
    """Return a MagicMock shaped like a Telethon Message."""
    from datetime import datetime, timedelta, timezone

    msg = MagicMock()
    msg.id = msg_id
    msg.text = text
    # Default to a recent timestamp so since-window filters (e.g. "7d") keep the
    # message. A hardcoded calendar date silently ages out and breaks read/search
    # tests once wall-clock passes it + the window. Tests that exercise the cutoff
    # set msg.date explicitly.
    msg.date = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    msg.media = MagicMock() if has_media else None
    msg.sender = MagicMock()
    msg.sender.username = "testuser"
    msg.reactions = None
    return msg


@pytest.fixture()
def mock_telethon(fake_session: Path):
    """
    Patch TelegramClient everywhere in arbling_telegram_mcp.client.
    Yields a configured mock instance. Reset the singleton _client after test.
    """
    import arbling_telegram_mcp.client as client_mod

    mock_instance = MagicMock()
    mock_instance.connect = AsyncMock()
    mock_instance.disconnect = AsyncMock()
    mock_instance.is_connected.return_value = True
    mock_instance.is_user_authorized = AsyncMock(return_value=True)

    me = MagicMock()
    me.first_name = "Test"
    me.last_name = "User"
    me.username = "testuser"
    me.phone = "97150123456"
    mock_instance.get_me = AsyncMock(return_value=me)

    mock_instance.iter_dialogs.return_value = AsyncIter([])
    mock_instance.iter_messages.return_value = AsyncIter([])
    mock_instance.get_messages = AsyncMock(return_value=None)

    with (
        patch("arbling_telegram_mcp.client.TelegramClient", return_value=mock_instance),
        # CLI functions import TelegramClient inside function bodies, so patch the source too
        patch("telethon.TelegramClient", return_value=mock_instance),
        patch.dict(
            "os.environ",
            {
                "TELEGRAM_API_ID": "12345",
                "TELEGRAM_API_HASH": "abcdef1234567890",
                "TELEGRAM_SESSION_PATH": str(fake_session),
            },
        ),
    ):
        # Force the singleton to reconnect with the mock
        client_mod._telegram_client._client = None
        yield mock_instance
        client_mod._telegram_client._client = None
