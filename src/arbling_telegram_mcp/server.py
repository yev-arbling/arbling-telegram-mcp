"""FastMCP server — registers all 7 Telegram read tools."""

from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from .client import (
    get_telegram_status,
    get_message_thread as _get_message_thread,
    list_my_groups as _list_my_groups,
    read_recent_messages as _read_recent_messages,
    refresh_session as _refresh_session,
    search_messages as _search_messages,
)
from .config import filter_by_category, load_curated_groups

mcp = FastMCP("arbling-telegram-mcp")


@mcp.tool()
async def telegram_status() -> dict:
    """
    Return connection and authentication status for this Telegram session.

    Returns: {connected, account_name, account_phone_masked, session_age_days,
              curated_group_count_by_category, last_error?}

    Call this first in a session to verify auth is alive before reading messages.
    If connected is False, the session may have expired — run
    'arbling-telegram-mcp auth' to re-authenticate.

    Privacy: This MCP server can read group/channel messages from your Telegram
    account. It cannot read DMs. It cannot send, react, or modify anything.
    """
    return await get_telegram_status()


@mcp.tool()
async def list_my_groups() -> list[dict]:
    """
    List every Telegram group and channel the user is a member of.

    Returns: [{id, name, type, participant_count, last_message_date}]
    type is 'group' | 'channel' | 'supergroup'.

    Does NOT return DMs or private chats — groups and channels only.
    May return 1000+ entries for active accounts. Use this once for
    discovery, then add chosen groups to curated-groups.yaml organized
    into tech_news / investor / tech_mentors categories.

    Privacy: Read-only. DMs are never included. No writes.
    """
    return await _list_my_groups()


@mcp.tool()
async def list_curated_groups(category: Optional[str] = None) -> list[dict]:
    """
    Return groups from the user's curated-groups.yaml config.

    Args:
        category: Filter to 'tech_news', 'investor', 'tech_mentors', or None (all).

    Returns: [{id, name, category}]

    If the config file is missing, returns an empty list with a note — recover
    by asking the user to run 'arbling-telegram-mcp list-groups' to create it.
    If you see an 'error' key in the result, the config is malformed.
    """
    try:
        config = load_curated_groups()
    except Exception as exc:
        return [{"error": str(exc), "id": None, "name": None, "category": None}]
    return filter_by_category(config, category)


@mcp.tool()
async def read_recent_messages(
    category: Optional[str] = None,
    since: str = "24h",
    limit: int = 100,
    group_id: Optional[int] = None,
) -> dict:
    """
    Read recent messages from curated Telegram groups.

    Args:
        category: 'tech_news' | 'investor' | 'tech_mentors' | None (all curated).
        since: Time window — '24h', '3d', '7d', or ISO date 'YYYY-MM-DD'.
        limit: Max messages per group (default 100, capped at 500).
        group_id: Read a single specific group (must be in curated-groups.yaml).
                  Raises an error if the group is not in the curated config.

    Returns: {messages: [{group_id, group_name, category, message_id, sender,
              date, text, link, has_media, reactions_count}],
              media_skipped, total}

    Messages sorted newest first. Media-only messages (no text) are skipped
    and counted in media_skipped. Only reads groups in curated-groups.yaml.

    Privacy: Read-only. Curated groups only. No DMs. No writes.
    """
    return await _read_recent_messages(
        category=category, since=since, limit=limit, group_id=group_id
    )


@mcp.tool()
async def search_messages(
    query: str,
    category: Optional[str] = None,
    since: str = "7d",
    limit: int = 50,
) -> list[dict]:
    """
    Full-text search across curated Telegram groups.

    Args:
        query: Case-insensitive search string.
        category: 'tech_news' | 'investor' | 'tech_mentors' | None (all curated).
        since: Time window — '24h', '3d', '7d', or ISO date 'YYYY-MM-DD'.
        limit: Max total results (default 50).

    Returns: [{group_id, group_name, category, message_id, sender, date,
               text, link, has_media, reactions_count, match_snippet}]

    match_snippet shows ±30 chars of context around the match.
    Only searches groups in curated-groups.yaml.

    Privacy: Read-only. Curated groups only. No DMs. No writes.
    """
    return await _search_messages(query=query, category=category, since=since, limit=limit)


@mcp.tool()
async def get_message_thread(
    group_id: int,
    message_id: int,
    max_replies: int = 20,
) -> dict:
    """
    Return a single message and its reply thread from a curated group.

    Args:
        group_id: Telegram chat ID (negative integer for groups/channels).
        message_id: Telegram message ID (visible in the 'link' field of read_recent_messages).
        max_replies: Maximum number of replies to fetch (default 20).

    Returns: {root_message: {...}, replies: [...]}
    Both root_message and each reply use the standard message shape.

    Use this when you spotted an interesting message and want the full discussion.
    Raises ValueError if the group is not in curated-groups.yaml.
    """
    return await _get_message_thread(
        group_id=group_id, message_id=message_id, max_replies=max_replies
    )


@mcp.tool()
async def refresh_session() -> dict:
    """
    Re-validate the Telegram session by making a live API call.

    Returns: {status: 'ok' | 'expired' | 'error', detail: str}

    'ok': session is valid.
    'expired': user logged out from another device or security action occurred.
               Run 'arbling-telegram-mcp auth' to re-authenticate (needs phone + SMS).
    'error': unexpected error — check 'detail' for the message.

    Does NOT auto-reauth. Interactive SMS code required.
    Call this when telegram_status reports connected=False or tools fail with auth errors.
    """
    return await _refresh_session()
