"""Entry point: dispatches auth / list-groups / status / default (MCP server)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


async def _cmd_auth() -> None:
    """Interactive first-time Telegram login via phone + SMS code."""
    api_id_str = os.environ.get("TELEGRAM_API_ID", "")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")

    if not api_id_str:
        print(
            "ERROR: TELEGRAM_API_ID is not set. "
            "Get your credentials at https://my.telegram.org",
            file=sys.stderr,
        )
        sys.exit(1)
    if not api_hash:
        print(
            "ERROR: TELEGRAM_API_HASH is not set. "
            "Get your credentials at https://my.telegram.org",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        api_id = int(api_id_str)
    except ValueError:
        print(f"ERROR: TELEGRAM_API_ID must be a number, got: {api_id_str!r}", file=sys.stderr)
        sys.exit(1)

    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError

    from .client import get_session_path

    session_path = get_session_path()
    _ensure_dir(session_path.parent)

    print(f"Authenticating to Telegram...")
    print(f"Session will be saved to: {session_path}.session")

    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.connect()

    try:
        if await client.is_user_authorized():
            me = await client.get_me()
            print(
                f"Already authenticated as {me.first_name} — session is valid. "
                "Nothing to do."
            )
            return

        phone = input(
            "Enter your phone number (with country code, e.g. +971501234567): "
        ).strip()
        await client.send_code_request(phone)

        code = input("Enter the verification code Telegram sent you: ").strip()

        try:
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            password = input(
                "Two-step verification is enabled. Enter your password: "
            ).strip()
            await client.sign_in(password=password)

        me = await client.get_me()
        print(f"\nAuthenticated as {me.first_name}!")
        print(f"Session saved to: {session_path}.session")
        print()
        print("Next steps:")
        print("  1. Discover your groups and create the curated config:")
        print(
            "     arbling-telegram-mcp list-groups "
            "> ~/.arbling-telegram-mcp/curated-groups.yaml"
        )
        print(
            "  2. Edit the YAML: move groups into tech_news / investor / tech_mentors"
        )
        print("  3. Add to your MCP client config — see README for the Claude Code snippet")
    finally:
        await client.disconnect()


async def _cmd_list_groups() -> None:
    """Fetch all groups and print a YAML-template to stdout."""
    from telethon import TelegramClient

    from .client import (
        _entity_type,
        _is_group_or_channel,
        get_api_credentials,
        get_session_path,
    )

    session_path = get_session_path()
    session_file = Path(str(session_path) + ".session")
    if not session_file.exists() and not session_path.exists():
        print(
            "ERROR: Session not found. Run 'arbling-telegram-mcp auth' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        api_id, api_hash = get_api_credentials()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        print(
            "ERROR: Session expired. Run 'arbling-telegram-mcp auth' to re-authenticate.",
            file=sys.stderr,
        )
        await client.disconnect()
        sys.exit(1)

    groups: list[dict] = []
    async for dialog in client.iter_dialogs():
        if not _is_group_or_channel(dialog):
            continue
        entity = dialog.entity
        groups.append(
            {
                "id": dialog.id,
                "name": dialog.name,
                "type": _entity_type(entity),
                "participant_count": getattr(entity, "participants_count", None),
            }
        )

    await client.disconnect()

    groups.sort(key=lambda g: g["name"].lower())

    print("# Curated groups config for arbling-telegram-mcp")
    print(
        "# Move groups from the reference list below into the 3 categories."
    )
    print("# Delete groups you don't want the MCP to read.")
    print("# Save this file to: ~/.arbling-telegram-mcp/curated-groups.yaml")
    print()
    print("tech_news: []")
    print()
    print("investor: []")
    print()
    print("tech_mentors: []")
    print()
    print()
    print(
        "# All groups you are a member of "
        "(reference — move into the categories above):"
    )
    for g in groups:
        count_str = (
            f"   ({g['participant_count']} members)"
            if g["participant_count"]
            else ""
        )
        name_escaped = g["name"].replace('"', '\\"')
        print(f'# - id: {g["id"]}   name: "{name_escaped}"{count_str}')


async def _cmd_status() -> None:
    """Print live connection/auth status as JSON."""
    from .client import get_telegram_status

    status = await get_telegram_status()
    print(json.dumps(status, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="arbling-telegram-mcp",
        description=(
            "Read-only MCP server that exposes curated Telegram groups "
            "to Claude Code / Cowork / any MCP client."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("auth", help="Interactive first-time Telegram login")
    sub.add_parser(
        "list-groups",
        help="Discover all groups and print a curated-groups.yaml template",
    )
    sub.add_parser("status", help="Print Telegram connection/auth status as JSON")
    sub.add_parser(
        "serve-http",
        help=(
            "Run the MCP server over streamable HTTP with bearer auth "
            "(hosted mode, e.g. Railway). Requires TELEGRAM_MCP_AUTH_TOKEN."
        ),
    )

    args = parser.parse_args()

    if args.command == "auth":
        asyncio.run(_cmd_auth())
    elif args.command == "list-groups":
        asyncio.run(_cmd_list_groups())
    elif args.command == "status":
        asyncio.run(_cmd_status())
    elif args.command == "serve-http":
        from .http_server import run_http_server

        try:
            run_http_server()
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            from .server import mcp
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        mcp.run()


if __name__ == "__main__":
    main()
