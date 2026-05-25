"""Tests for client.py: parse helpers, DM filtering, curated-only enforcement."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arbling_telegram_mcp.client import _mask_phone, _parse_since
from tests.conftest import AsyncIter, _make_mock_dialog, _make_mock_message


# ---------------------------------------------------------------------------
# _parse_since
# ---------------------------------------------------------------------------


def test_parse_since_24h():
    dt = _parse_since("24h")
    now = datetime.now(tz=timezone.utc)
    assert (now - dt) > timedelta(hours=23)
    assert (now - dt) < timedelta(hours=25)


def test_parse_since_3d():
    dt = _parse_since("3d")
    now = datetime.now(tz=timezone.utc)
    diff = now - dt
    assert timedelta(days=2, hours=23) < diff < timedelta(days=3, hours=1)


def test_parse_since_7d():
    dt = _parse_since("7d")
    now = datetime.now(tz=timezone.utc)
    diff = now - dt
    assert timedelta(days=6, hours=23) < diff < timedelta(days=7, hours=1)


def test_parse_since_iso_date():
    dt = _parse_since("2026-05-20")
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.day == 20
    assert dt.tzinfo is not None


def test_parse_since_invalid_raises():
    with pytest.raises(ValueError, match="Cannot parse"):
        _parse_since("yesterday")


def test_parse_since_invalid_unit_raises():
    with pytest.raises(ValueError, match="Cannot parse"):
        _parse_since("5w")


# ---------------------------------------------------------------------------
# _mask_phone
# ---------------------------------------------------------------------------


def test_mask_phone_standard():
    masked = _mask_phone("+97150123456")
    assert masked.startswith("+971")
    assert "*" in masked
    assert masked.endswith("56")


def test_mask_phone_short():
    masked = _mask_phone("+1")
    assert masked == "+1"


def test_mask_phone_empty():
    assert _mask_phone("") == ""


# ---------------------------------------------------------------------------
# list_my_groups — DM filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_my_groups_excludes_dms(mock_telethon, fake_config: Path):
    channel_dialog = _make_mock_dialog(-1001111111111, "Tech Group", entity_type="channel")
    dm_dialog = _make_mock_dialog(123456, "A Person", entity_type="user")
    chat_dialog = _make_mock_dialog(-100222222, "Team Chat", entity_type="chat")

    mock_telethon.iter_dialogs.return_value = AsyncIter(
        [channel_dialog, dm_dialog, chat_dialog]
    )

    import arbling_telegram_mcp.client as client_mod

    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_PATH": str(fake_config)}):
        groups = await client_mod.list_my_groups()

    assert len(groups) == 2
    ids = [g["id"] for g in groups]
    assert -1001111111111 in ids
    assert -100222222 in ids
    assert 123456 not in ids


@pytest.mark.asyncio
async def test_list_my_groups_all_dms_returns_empty(mock_telethon, fake_config: Path):
    dm1 = _make_mock_dialog(1, "Person 1", entity_type="user")
    dm2 = _make_mock_dialog(2, "Person 2", entity_type="user")
    mock_telethon.iter_dialogs.return_value = AsyncIter([dm1, dm2])

    import arbling_telegram_mcp.client as client_mod

    groups = await client_mod.list_my_groups()
    assert groups == []


# ---------------------------------------------------------------------------
# read_recent_messages — curated-only enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_recent_messages_rejects_non_curated_group(
    mock_telethon, fake_config: Path
):
    import arbling_telegram_mcp.client as client_mod

    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_PATH": str(fake_config)}):
        with pytest.raises(ValueError, match="not in curated-groups.yaml"):
            await client_mod.read_recent_messages(group_id=-9999999999)


@pytest.mark.asyncio
async def test_read_recent_messages_skips_media_only_messages(
    mock_telethon, fake_config: Path
):
    text_msg = _make_mock_message(msg_id=1, text="Hello", has_media=False)
    media_msg = _make_mock_message(msg_id=2, text="", has_media=True)

    mock_telethon.iter_messages.return_value = AsyncIter([text_msg, media_msg])

    import arbling_telegram_mcp.client as client_mod

    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_PATH": str(fake_config)}):
        result = await client_mod.read_recent_messages(
            category="tech_news", since="7d"
        )

    assert result["media_skipped"] >= 1
    assert all(m["text"] != "" for m in result["messages"])


@pytest.mark.asyncio
async def test_read_recent_messages_respects_since_cutoff(
    mock_telethon, fake_config: Path
):
    old_msg = _make_mock_message(msg_id=1, text="Old message")
    old_msg.date = datetime(2020, 1, 1, tzinfo=timezone.utc)

    recent_msg = _make_mock_message(msg_id=2, text="Recent message")
    recent_msg.date = datetime.now(tz=timezone.utc) - timedelta(hours=1)

    # Return old message first (iter_messages would return newest-first, but
    # for this test we simulate: recent first, old second → loop breaks on old)
    call_count = 0

    async def make_iter(*args, **kwargs):
        yield recent_msg
        yield old_msg

    mock_telethon.iter_messages.side_effect = make_iter

    import arbling_telegram_mcp.client as client_mod

    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_PATH": str(fake_config)}):
        result = await client_mod.read_recent_messages(
            category="tech_news", since="24h"
        )

    texts = [m["text"] for m in result["messages"]]
    assert "Recent message" in texts
    assert "Old message" not in texts


# ---------------------------------------------------------------------------
# search_messages — curated-only, match_snippet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_messages_includes_match_snippet(
    mock_telethon, fake_config: Path
):
    msg = _make_mock_message(
        msg_id=10, text="This is a test message about artificial intelligence."
    )
    mock_telethon.iter_messages.return_value = AsyncIter([msg])

    import arbling_telegram_mcp.client as client_mod

    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_PATH": str(fake_config)}):
        results = await client_mod.search_messages(query="intelligence", since="7d")

    assert len(results) >= 1
    assert "match_snippet" in results[0]
    assert "intelligence" in results[0]["match_snippet"].lower()


# ---------------------------------------------------------------------------
# get_message_thread — curated-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_message_thread_rejects_non_curated(
    mock_telethon, fake_config: Path
):
    import arbling_telegram_mcp.client as client_mod

    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_PATH": str(fake_config)}):
        with pytest.raises(ValueError, match="not in curated-groups.yaml"):
            await client_mod.get_message_thread(
                group_id=-9999999, message_id=1
            )
