"""Telethon MTProto client wrapper for arbling-telegram-mcp."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dateutil import parser as dateutil_parser
from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.sessions import SQLiteSession, StringSession
from telethon.tl.types import Channel, Chat, User

from .config import ConfigError, filter_by_category, get_all_curated_ids, load_curated_groups

logger = logging.getLogger(__name__)

DEFAULT_SESSION_PATH = Path.home() / ".arbling-telegram-mcp" / "session"

# How long a connection will wait on a locked session DB before raising
# "database is locked". Telethon's SQLiteSession opens sqlite3.connect()
# with no explicit timeout, which defaults to 5s — too short when several
# arbling-telegram-mcp server processes (e.g. leftover from past Claude
# Code sessions that weren't cleanly closed) are alive at once and all
# point at the same local session file.
_SQLITE_BUSY_TIMEOUT_SECONDS = 30


class _ResilientSQLiteSession(SQLiteSession):
    """SQLiteSession with a longer busy timeout and WAL journal mode.

    WAL mode lets concurrent readers proceed without blocking on a writer,
    and the extended busy_timeout makes any remaining write/write
    contention retry instead of failing immediately with "database is
    locked". Only one local server is expected to hold this session at a
    time; this is a safety net for the transient case where more than one
    briefly overlaps (e.g. during a restart) rather than a substitute for
    running multiple long-lived servers against the same session file.

    Local SQLite session path only — never used for the hosted-mode
    TELEGRAM_SESSION_STRING (StringSession) branch, which holds no on-disk
    file and cannot hit this class of contention.
    """

    def _cursor(self):
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.filename,
                check_same_thread=False,
                timeout=_SQLITE_BUSY_TIMEOUT_SECONDS,
            )
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute(
                    f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_SECONDS * 1000}"
                )
            except sqlite3.Error:
                # Non-fatal: another connection may prevent the WAL switch
                # from taking effect immediately. The busy_timeout on this
                # connection object still applies via the timeout= kwarg.
                logger.warning(
                    "Could not set WAL/busy_timeout pragmas on %s", self.filename
                )
        return self._conn.cursor()


def get_session_path() -> Path:
    raw = os.environ.get("TELEGRAM_SESSION_PATH", "")
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_SESSION_PATH


def get_session_string() -> str:
    """Return TELEGRAM_SESSION_STRING with whitespace and UTF-8 BOM stripped.

    The value is a credential equivalent to a full login — it must never be
    logged, echoed, or included in error messages.
    """
    raw = os.environ.get("TELEGRAM_SESSION_STRING", "")
    return raw.replace("\ufeff", "").strip()


def get_api_credentials() -> tuple[int, str]:
    api_id_str = os.environ.get("TELEGRAM_API_ID", "")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    if not api_id_str:
        raise RuntimeError(
            "TELEGRAM_API_ID environment variable is not set. "
            "Get your credentials at https://my.telegram.org"
        )
    if not api_hash:
        raise RuntimeError(
            "TELEGRAM_API_HASH environment variable is not set. "
            "Get your credentials at https://my.telegram.org"
        )
    try:
        api_id = int(api_id_str)
    except ValueError:
        raise RuntimeError(
            f"TELEGRAM_API_ID must be a number, got: {api_id_str!r}"
        )
    return api_id, api_hash


def _mask_phone(phone: str) -> str:
    """Mask phone number for safe display, e.g. +97150*****12."""
    if not phone:
        return ""
    digits = re.sub(r"[^\d+]", "", phone)
    if len(digits) <= 4:
        return digits
    visible_tail = 2
    visible_head = min(4, len(digits) - visible_tail)
    stars = max(0, len(digits) - visible_head - visible_tail)
    return digits[:visible_head] + "*" * stars + digits[-visible_tail:]


def _parse_since(since: str) -> datetime:
    """Parse since string to a UTC-aware datetime.

    Accepts: '24h', '3d', '7d', or ISO date 'YYYY-MM-DD'.
    """
    now = datetime.now(tz=timezone.utc)
    since = since.strip()
    if since.endswith("h"):
        try:
            return now - timedelta(hours=int(since[:-1]))
        except ValueError:
            pass
    if since.endswith("d"):
        try:
            return now - timedelta(days=int(since[:-1]))
        except ValueError:
            pass
    try:
        dt = dateutil_parser.parse(since)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        raise ValueError(
            f"Cannot parse 'since' value: {since!r}. "
            "Use '24h', '3d', '7d', or an ISO date like '2026-05-20'."
        )


def _is_group_or_channel(dialog) -> bool:
    """Return True only for groups, supergroups, and channels — not DMs."""
    entity = dialog.entity
    if isinstance(entity, User):
        return False
    return isinstance(entity, (Channel, Chat))


def _entity_type(entity) -> str:
    if isinstance(entity, Channel):
        return "supergroup" if entity.megagroup else "channel"
    if isinstance(entity, Chat):
        return "group"
    return "unknown"


def _format_message(
    msg, group_id: int, group_name: str, category: str
) -> dict:
    """Convert a Telethon Message into the standard tool response shape."""
    sender_name = "unknown"
    if msg.sender:
        if hasattr(msg.sender, "username") and msg.sender.username:
            sender_name = f"@{msg.sender.username}"
        elif hasattr(msg.sender, "first_name"):
            parts = [
                p
                for p in (
                    getattr(msg.sender, "first_name", None),
                    getattr(msg.sender, "last_name", None),
                )
                if p
            ]
            sender_name = " ".join(parts) or "unknown"
        elif hasattr(msg.sender, "title") and msg.sender.title:
            sender_name = msg.sender.title

    has_media = msg.media is not None

    reactions_count = 0
    if hasattr(msg, "reactions") and msg.reactions:
        reactions = msg.reactions
        if hasattr(reactions, "results") and reactions.results:
            reactions_count = sum(
                getattr(r, "count", 0) for r in reactions.results
            )

    # Build t.me/c/<channel_id>/<msg_id> deep link
    group_id_str = str(group_id)
    if group_id_str.startswith("-100"):
        channel_id = group_id_str[4:]
    else:
        channel_id = group_id_str.lstrip("-")
    link = f"https://t.me/c/{channel_id}/{msg.id}"

    return {
        "group_id": group_id,
        "group_name": group_name,
        "category": category,
        "message_id": msg.id,
        "sender": sender_name,
        "date": msg.date.isoformat() if msg.date else None,
        "text": msg.text or "",
        "link": link,
        "has_media": has_media,
        "reactions_count": reactions_count,
    }


class TelegramMCPClient:
    """Singleton Telethon session used by all MCP tools."""

    def __init__(self) -> None:
        self._client: Optional[TelegramClient] = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> TelegramClient:
        client = self._client
        if client is not None and client.is_connected():
            return client

        async with self._lock:
            # Re-check under the lock: a concurrent caller may have finished
            # initializing while we were waiting.
            client = self._client
            if client is not None and client.is_connected():
                return client

            api_id, api_hash = get_api_credentials()

            session_string = get_session_string()
            if session_string:
                # Hosted mode: TELEGRAM_SESSION_STRING takes precedence over
                # any session file. Never include the value in errors or logs.
                try:
                    session = StringSession(session_string)
                except Exception:
                    raise RuntimeError(
                        "TELEGRAM_SESSION_STRING is set but is not a valid "
                        "Telethon string session (value not shown). Re-export "
                        "it with scripts/export_session_to_railway.py."
                    ) from None
            else:
                session_path = get_session_path()
                session_file = Path(str(session_path) + ".session")
                if not session_file.exists() and not session_path.exists():
                    raise RuntimeError(
                        f"Session not initialized: no session file at {session_file} "
                        "and no TELEGRAM_SESSION_STRING set. Run "
                        "'arbling-telegram-mcp auth' to create a session file, or "
                        "set TELEGRAM_SESSION_STRING (hosted mode)."
                    )
                # Local file session only (never the hosted StringSession
                # path above): use the WAL/busy-timeout-hardened session so
                # a leftover local process holding the file doesn't surface
                # as "database is locked".
                session = _ResilientSQLiteSession(str(session_path))

            # Work on a local variable across the awaits; publish to
            # self._client only once fully connected and authorized.
            client = TelegramClient(session, api_id, api_hash)
            await client.connect()

            if not await client.is_user_authorized():
                # connect() succeeded but the session is expired/revoked —
                # tear the socket down before raising so we never leak a
                # live, connected-but-unauthorized client that a later call
                # would otherwise reuse (client.is_connected() would still
                # be True even though it's unusable).
                await client.disconnect()
                raise RuntimeError(
                    "Session expired or unauthorized. "
                    "Run 'arbling-telegram-mcp auth' to re-authenticate."
                )

            self._client = client
            return client

    async def get_status(self) -> dict:
        try:
            client = await self._get_client()
            me = await client.get_me()

            session_path = get_session_path()
            session_file = Path(str(session_path) + ".session")
            session_age_days: Optional[float] = None
            if session_file.exists():
                age_seconds = time.time() - session_file.stat().st_mtime
                session_age_days = round(age_seconds / 86400, 1)

            try:
                config = load_curated_groups()
                curated_counts = {cat: len(groups) for cat, groups in config.items()}
            except ConfigError as exc:
                curated_counts = {"error": str(exc)}

            name_parts = [
                p
                for p in (
                    getattr(me, "first_name", None),
                    getattr(me, "last_name", None),
                )
                if p
            ]
            account_name = " ".join(name_parts) or getattr(me, "username", "unknown")
            phone = getattr(me, "phone", "") or ""

            return {
                "connected": True,
                "account_name": account_name,
                "account_phone_masked": _mask_phone(phone),
                "session_age_days": session_age_days,
                "curated_group_count_by_category": curated_counts,
            }
        except Exception as exc:
            return {"connected": False, "last_error": str(exc)}

    async def list_my_groups(self) -> list[dict]:
        client = await self._get_client()
        groups: list[dict] = []
        async for dialog in client.iter_dialogs():
            if not _is_group_or_channel(dialog):
                continue
            entity = dialog.entity
            participant_count = getattr(entity, "participants_count", None)
            last_msg_date = None
            if dialog.message and dialog.message.date:
                last_msg_date = dialog.message.date.isoformat()
            groups.append(
                {
                    "id": dialog.id,
                    "name": dialog.name,
                    "type": _entity_type(entity),
                    "participant_count": participant_count,
                    "last_message_date": last_msg_date,
                }
            )
        return groups

    async def read_recent_messages(
        self,
        category: Optional[str],
        since: str,
        limit: int,
        group_id: Optional[int],
    ) -> dict:
        since_dt = _parse_since(since)
        limit = min(limit, 500)

        try:
            config = load_curated_groups()
        except ConfigError as exc:
            return {"messages": [], "media_skipped": 0, "total": 0, "error": str(exc)}

        curated_ids = get_all_curated_ids(config)

        if group_id is not None:
            if group_id not in curated_ids:
                raise ValueError(
                    f"Group {group_id} is not in curated-groups.yaml. "
                    "Edit the config to include it."
                )
            target_groups = [
                g
                for groups in config.values()
                for g in groups
                if g["id"] == group_id
            ]
        elif category is not None:
            target_groups = list(config.get(category, []))
        else:
            target_groups = [g for groups in config.values() for g in groups]

        client = await self._get_client()
        all_messages: list[dict] = []
        media_skip_count = 0

        for group in target_groups:
            try:
                async for msg in client.iter_messages(group["id"], limit=limit):
                    if msg.date and msg.date < since_dt:
                        break
                    if not msg.text:
                        media_skip_count += 1
                        continue
                    all_messages.append(
                        _format_message(msg, group["id"], group["name"], group["category"])
                    )
            except FloodWaitError as exc:
                if exc.seconds > 5:
                    logger.warning(
                        "Telegram flood wait: %ds for group %s", exc.seconds, group["name"]
                    )
                await asyncio.sleep(exc.seconds)
            except Exception as exc:
                logger.warning("Failed to read group %s: %s", group["name"], exc)

        all_messages.sort(key=lambda m: m["date"] or "", reverse=True)

        return {
            "messages": all_messages,
            "media_skipped": media_skip_count,
            "total": len(all_messages),
        }

    async def search_messages(
        self,
        query: str,
        category: Optional[str],
        since: str,
        limit: int,
    ) -> list[dict]:
        since_dt = _parse_since(since)
        limit = min(limit, 500)
        pattern = re.compile(re.escape(query), re.IGNORECASE)

        try:
            config = load_curated_groups()
        except ConfigError:
            return []

        target_groups = (
            list(config.get(category, []))
            if category is not None
            else [g for groups in config.values() for g in groups]
        )

        client = await self._get_client()
        all_messages: list[dict] = []

        for group in target_groups:
            if len(all_messages) >= limit:
                break
            try:
                async for msg in client.iter_messages(
                    group["id"], search=query, limit=limit
                ):
                    if msg.date and msg.date < since_dt:
                        break
                    if not msg.text:
                        continue
                    formatted = _format_message(
                        msg, group["id"], group["name"], group["category"]
                    )
                    m = pattern.search(msg.text)
                    if m:
                        start = max(0, m.start() - 30)
                        end = min(len(msg.text), m.end() + 30)
                        snippet = (
                            ("..." if start > 0 else "")
                            + msg.text[start:end]
                            + ("..." if end < len(msg.text) else "")
                        )
                    else:
                        snippet = msg.text[:60]
                    formatted["match_snippet"] = snippet
                    all_messages.append(formatted)
                    if len(all_messages) >= limit:
                        break
            except FloodWaitError as exc:
                if exc.seconds > 5:
                    logger.warning(
                        "Telegram flood wait: %ds for group %s", exc.seconds, group["name"]
                    )
                await asyncio.sleep(exc.seconds)
            except Exception as exc:
                logger.warning("Failed to search group %s: %s", group["name"], exc)

        return all_messages

    async def get_message_thread(
        self, group_id: int, message_id: int, max_replies: int
    ) -> dict:
        try:
            config = load_curated_groups()
        except ConfigError as exc:
            raise ValueError(f"Config error: {exc}")

        curated_ids = get_all_curated_ids(config)
        if group_id not in curated_ids:
            raise ValueError(
                f"Group {group_id} is not in curated-groups.yaml. "
                "Edit the config to include it."
            )

        group_info: Optional[dict] = next(
            (g for groups in config.values() for g in groups if g["id"] == group_id),
            None,
        )

        client = await self._get_client()

        root_msg = await client.get_messages(group_id, ids=message_id)
        if root_msg is None:
            raise ValueError(f"Message {message_id} not found in group {group_id}")

        group_name = group_info["name"] if group_info else str(group_id)
        category = group_info["category"] if group_info else ""
        root_formatted = _format_message(root_msg, group_id, group_name, category)

        replies: list[dict] = []
        try:
            async for reply in client.iter_messages(
                group_id, reply_to=message_id, limit=max_replies
            ):
                if reply.text:
                    replies.append(
                        _format_message(reply, group_id, group_name, category)
                    )
        except Exception as exc:
            logger.warning("Failed to get replies for message %d: %s", message_id, exc)

        return {"root_message": root_formatted, "replies": replies}

    async def refresh_session(self) -> dict:
        try:
            client = await self._get_client()
            me = await client.get_me()
            if me is None:
                return {
                    "status": "expired",
                    "detail": (
                        "No user returned from Telegram. "
                        "Run 'arbling-telegram-mcp auth' to re-authenticate."
                    ),
                }
            username = getattr(me, "username", None) or getattr(me, "first_name", "unknown")
            return {"status": "ok", "detail": f"Session valid for {username}"}
        except RuntimeError as exc:
            msg = str(exc)
            if "expired" in msg.lower() or "unauthorized" in msg.lower():
                return {"status": "expired", "detail": msg}
            return {"status": "error", "detail": msg}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected():
            await self._client.disconnect()


# ---------------------------------------------------------------------------
# Module-level singleton + public API used by server.py
# ---------------------------------------------------------------------------

_telegram_client = TelegramMCPClient()


async def get_telegram_status() -> dict:
    return await _telegram_client.get_status()


async def list_my_groups() -> list[dict]:
    return await _telegram_client.list_my_groups()


async def read_recent_messages(
    category: Optional[str] = None,
    since: str = "24h",
    limit: int = 100,
    group_id: Optional[int] = None,
) -> dict:
    return await _telegram_client.read_recent_messages(category, since, limit, group_id)


async def search_messages(
    query: str,
    category: Optional[str] = None,
    since: str = "7d",
    limit: int = 50,
) -> list[dict]:
    return await _telegram_client.search_messages(query, category, since, limit)


async def get_message_thread(
    group_id: int,
    message_id: int,
    max_replies: int = 20,
) -> dict:
    return await _telegram_client.get_message_thread(group_id, message_id, max_replies)


async def refresh_session() -> dict:
    return await _telegram_client.refresh_session()
