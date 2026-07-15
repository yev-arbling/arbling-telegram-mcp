#!/usr/bin/env python
"""Export the local Telethon SQLite session to Railway as TELEGRAM_SESSION_STRING.

Runs entirely on the founder's laptop and entirely offline — the SQLite
session file is converted to a Telethon StringSession without any network
call, then handed to the Railway CLI as an environment variable.

The session string is a credential equivalent to a full Telegram login:
it is never printed, logged, or passed through a shell. Only its length
is reported.

Usage:
    py -3.12 scripts/export_session_to_railway.py [--service NAME] [--environment NAME]

Prerequisites:
    - a local session created by `arbling-telegram-mcp auth`
      (default ~/.arbling-telegram-mcp/session, override: TELEGRAM_SESSION_PATH)
    - Railway CLI installed and logged in, project linked (`railway link`)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

DEFAULT_SESSION_PATH = Path.home() / ".arbling-telegram-mcp" / "session"
SESSION_STRING_VAR = "TELEGRAM_SESSION_STRING"


def get_local_session_path() -> Path:
    raw = os.environ.get("TELEGRAM_SESSION_PATH", "")
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_SESSION_PATH


def convert_session_to_string(session_path: Path) -> str:
    """Load the SQLite session from disk and convert it to a string session.

    Offline: SQLiteSession reads the local file; StringSession.save() only
    packs dc_id / server address / port / auth key — no network involved.
    """
    from telethon.sessions import SQLiteSession, StringSession

    session_file = Path(str(session_path) + ".session")
    if not session_file.exists():
        raise RuntimeError(
            f"No session file found at {session_file}. "
            "Run 'arbling-telegram-mcp auth' first."
        )

    sqlite_session = SQLiteSession(str(session_path))
    try:
        session_string = StringSession.save(sqlite_session)
    finally:
        sqlite_session.close()

    if not session_string:
        raise RuntimeError(
            f"Session file {session_file} exists but holds no auth key "
            "(login never completed?). Run 'arbling-telegram-mcp auth' first."
        )
    return session_string


def set_railway_variable(
    session_string: str,
    service: Optional[str] = None,
    environment: Optional[str] = None,
) -> None:
    """Set TELEGRAM_SESSION_STRING on Railway via the CLI.

    Always an argument list (never shell=True) so the value is not exposed
    to shell parsing/history. CLI output is captured and discarded because
    the Railway CLI may echo variable values back.
    """
    railway = shutil.which("railway")
    if railway is None:
        raise RuntimeError(
            "Railway CLI not found on PATH. Install it first: npm i -g @railway/cli"
        )

    cmd = [railway, "variables", "--set", f"{SESSION_STRING_VAR}={session_string}"]
    if service:
        cmd.extend(["--service", service])
    if environment:
        cmd.extend(["--environment", environment])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"railway CLI exited with code {result.returncode}. Its output is "
            "suppressed because it may contain the session string. Check "
            "'railway whoami' and 'railway status', then retry."
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert the local Telethon session to a StringSession (offline) "
            "and set it as TELEGRAM_SESSION_STRING on Railway. The value is "
            "never printed."
        ),
    )
    parser.add_argument("--service", default=None, help="Railway service name")
    parser.add_argument(
        "--environment", default=None, help="Railway environment name"
    )
    args = parser.parse_args(argv)

    try:
        session_string = convert_session_to_string(get_local_session_path())
        set_railway_variable(session_string, args.service, args.environment)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"{SESSION_STRING_VAR} set on Railway.")
    print(f"Session string length: {len(session_string)} characters (value not shown).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
