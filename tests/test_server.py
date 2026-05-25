"""MCP tool integration tests: each tool is callable and returns the expected shape."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# telegram_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telegram_status_returns_dict():
    expected = {
        "connected": True,
        "account_name": "Test User",
        "account_phone_masked": "+971*****56",
        "session_age_days": 0.5,
        "curated_group_count_by_category": {"tech_news": 2, "investor": 1, "tech_mentors": 1},
    }
    with patch(
        "arbling_telegram_mcp.server.get_telegram_status",
        new_callable=AsyncMock,
        return_value=expected,
    ):
        from arbling_telegram_mcp.server import telegram_status

        result = await telegram_status()

    assert result["connected"] is True
    assert "account_name" in result
    assert "curated_group_count_by_category" in result


# ---------------------------------------------------------------------------
# list_my_groups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_my_groups_returns_list():
    groups = [
        {"id": -1001111, "name": "A", "type": "channel", "participant_count": 100, "last_message_date": None},
        {"id": -1002222, "name": "B", "type": "supergroup", "participant_count": 50, "last_message_date": None},
    ]
    with patch(
        "arbling_telegram_mcp.server._list_my_groups",
        new_callable=AsyncMock,
        return_value=groups,
    ):
        from arbling_telegram_mcp.server import list_my_groups

        result = await list_my_groups()

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["id"] == -1001111


# ---------------------------------------------------------------------------
# list_curated_groups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_curated_groups_all(fake_config: Path):
    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_PATH": str(fake_config)}):
        from arbling_telegram_mcp.server import list_curated_groups

        result = await list_curated_groups(category=None)

    assert isinstance(result, list)
    assert len(result) == 4  # 2 tech_news + 1 investor + 1 tech_mentors
    categories = {g["category"] for g in result}
    assert "tech_news" in categories


@pytest.mark.asyncio
async def test_list_curated_groups_filtered(fake_config: Path):
    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_PATH": str(fake_config)}):
        from arbling_telegram_mcp.server import list_curated_groups

        result = await list_curated_groups(category="investor")

    assert all(g["category"] == "investor" for g in result)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_curated_groups_missing_file_returns_empty(tmp_path: Path):
    nonexistent = str(tmp_path / "none.yaml")
    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_PATH": nonexistent}):
        from arbling_telegram_mcp.server import list_curated_groups

        result = await list_curated_groups()

    assert result == []


# ---------------------------------------------------------------------------
# read_recent_messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_recent_messages_returns_expected_shape():
    payload = {
        "messages": [
            {
                "group_id": -1001234567890,
                "group_name": "MCP Developers",
                "category": "tech_news",
                "message_id": 42,
                "sender": "@alice",
                "date": "2026-05-25T12:00:00+00:00",
                "text": "Hello world",
                "link": "https://t.me/c/1234567890/42",
                "has_media": False,
                "reactions_count": 3,
            }
        ],
        "media_skipped": 2,
        "total": 1,
    }
    with patch(
        "arbling_telegram_mcp.server._read_recent_messages",
        new_callable=AsyncMock,
        return_value=payload,
    ):
        from arbling_telegram_mcp.server import read_recent_messages

        result = await read_recent_messages(category="tech_news", since="24h")

    assert "messages" in result
    assert "media_skipped" in result
    assert "total" in result
    assert result["messages"][0]["sender"] == "@alice"


# ---------------------------------------------------------------------------
# search_messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_messages_returns_list():
    hits = [
        {
            "group_id": -1001234567890,
            "group_name": "MCP Developers",
            "category": "tech_news",
            "message_id": 99,
            "sender": "@bob",
            "date": "2026-05-24T08:00:00+00:00",
            "text": "MCP is great for AI agents",
            "link": "https://t.me/c/1234567890/99",
            "has_media": False,
            "reactions_count": 0,
            "match_snippet": "...MCP is great...",
        }
    ]
    with patch(
        "arbling_telegram_mcp.server._search_messages",
        new_callable=AsyncMock,
        return_value=hits,
    ):
        from arbling_telegram_mcp.server import search_messages

        result = await search_messages(query="MCP", since="7d")

    assert isinstance(result, list)
    assert result[0]["match_snippet"] == "...MCP is great..."


# ---------------------------------------------------------------------------
# get_message_thread
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_message_thread_returns_root_and_replies():
    thread = {
        "root_message": {
            "group_id": -1001234567890,
            "group_name": "MCP Developers",
            "category": "tech_news",
            "message_id": 10,
            "sender": "@alice",
            "date": "2026-05-25T10:00:00+00:00",
            "text": "What do you think about FastMCP?",
            "link": "https://t.me/c/1234567890/10",
            "has_media": False,
            "reactions_count": 5,
        },
        "replies": [
            {
                "group_id": -1001234567890,
                "group_name": "MCP Developers",
                "category": "tech_news",
                "message_id": 11,
                "sender": "@bob",
                "date": "2026-05-25T10:05:00+00:00",
                "text": "Love it!",
                "link": "https://t.me/c/1234567890/11",
                "has_media": False,
                "reactions_count": 2,
            }
        ],
    }
    with patch(
        "arbling_telegram_mcp.server._get_message_thread",
        new_callable=AsyncMock,
        return_value=thread,
    ):
        from arbling_telegram_mcp.server import get_message_thread

        result = await get_message_thread(group_id=-1001234567890, message_id=10)

    assert "root_message" in result
    assert "replies" in result
    assert len(result["replies"]) == 1


# ---------------------------------------------------------------------------
# refresh_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_session_ok():
    with patch(
        "arbling_telegram_mcp.server._refresh_session",
        new_callable=AsyncMock,
        return_value={"status": "ok", "detail": "Session valid for testuser"},
    ):
        from arbling_telegram_mcp.server import refresh_session

        result = await refresh_session()

    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_refresh_session_expired():
    with patch(
        "arbling_telegram_mcp.server._refresh_session",
        new_callable=AsyncMock,
        return_value={"status": "expired", "detail": "Session expired"},
    ):
        from arbling_telegram_mcp.server import refresh_session

        result = await refresh_session()

    assert result["status"] == "expired"
