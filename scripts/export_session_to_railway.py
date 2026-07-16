#!/usr/bin/env python
"""Export the local Telethon SQLite session to Railway as TELEGRAM_SESSION_STRING.

Runs entirely on the founder's laptop and entirely offline — the SQLite
session file is converted to a Telethon StringSession without any network
call, then piped to the Railway CLI over stdin (`railway variable set
<KEY> --stdin`) so the credential is never a process argument.

The session string is a credential equivalent to a full Telegram login:
it is never printed, logged, passed through a shell, or placed on the
command line. Only its length is reported.

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

    Sent over the child process's stdin pipe via `railway variable set
    <KEY> --stdin` (Railway CLI >= v4.56.0, released 2026-05-08) rather than
    `--set KEY=value`, so the credential never appears as a process argument
    at all — no window during which `ps`/Task Manager on this laptop (or any
    other local user) could read it out of the argv of a running process.
    Always an argument list (never shell=True). CLI output is captured and
    discarded because the Railway CLI may echo variable values back.
    """
    railway = shutil.which("railway")
    if railway is None:
        raise RuntimeError(
            "Railway CLI not found on PATH. Install it first: npm i -g @railway/cli"
        )

    cmd = [railway, "variable", "set", SESSION_STRING_VAR, "--stdin"]
    if service:
        cmd.extend(["--service", service])
    if environment:
        cmd.extend(["--environment", environment])

    result = subprocess.run(cmd, input=session_string, capture_output=True, text=True)
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
