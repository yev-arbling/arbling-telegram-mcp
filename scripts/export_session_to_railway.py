#!/usr/bin/env python
"""Export a Telethon session to Railway as TELEGRAM_SESSION_STRING.

Two modes:

Default (no flag) — convert the LOCAL session file. Entirely offline: the
SQLite session is converted to a Telethon StringSession without any network
call. SHARED-KEY HAZARD: the exported string carries the SAME auth key as
the local session file. If any other client (e.g. the local telegram MCP on
this laptop) keeps using that key while the hosted deployment uses it from
another IP address, Telegram permanently revokes the key for BOTH sides
(AuthKeyDuplicatedError) — and the OLD local session file is dead too: the
next local use will require a full re-login.

--fresh-login — mint a BRAND-NEW session. Requires network: performs
Telethon's interactive login (phone number + login code + optional 2FA
password, prompted by Telethon itself on the terminal) on a brand-new
StringSession. The hosted deployment then owns a dedicated auth key that
can never collide with the laptop's session. Recommended for hosted
deployments.

Either way, the string is piped to the Railway CLI over stdin (`railway
variable set <KEY> --stdin`) so the credential is never a process argument.

The session string is a credential equivalent to a full Telegram login:
it is never printed, logged, passed through a shell, or placed on the
command line. Only its length is reported.

Usage:
    py -3.12 scripts/export_session_to_railway.py [--fresh-login] [--service NAME] [--environment NAME]

Prerequisites:
    - default mode: a local session created by `arbling-telegram-mcp auth`
      (default ~/.arbling-telegram-mcp/session, override: TELEGRAM_SESSION_PATH)
    - --fresh-login: TELEGRAM_API_ID / TELEGRAM_API_HASH env vars + network access
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

DEFAULT_MODE_WARNING = """\
================================================================================
WARNING: default mode converts the LOCAL session file — the exported string
SHARES that session's auth key. If any other client (e.g. the local telegram
MCP on this laptop) keeps using the same key while the hosted deployment uses
it from another IP address, Telegram will PERMANENTLY revoke the key for BOTH
sides (AuthKeyDuplicatedError), and the old local session file dies with it:
the next local use will require a full re-login.
For hosted deployments, use --fresh-login so the host owns its own auth key.
================================================================================"""

HELP_EPILOG = """\
modes:
  default        convert the existing LOCAL session file (offline). The exported
                 string SHARES the local session's auth key: if the laptop keeps
                 using that key while the hosted deployment uses it from another
                 IP address, Telegram permanently revokes the key for BOTH sides
                 (AuthKeyDuplicatedError). After that, the OLD local session
                 file is dead too — the next local use requires a full re-login.
  --fresh-login  interactive Telethon login (REQUIRES NETWORK) that mints a
                 brand-new StringSession with its own dedicated auth key. The
                 hosted deployment then owns its key outright and can never
                 collide with the laptop's session. Recommended for hosted
                 deployments. Needs TELEGRAM_API_ID / TELEGRAM_API_HASH set.
"""


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


def get_api_credentials() -> tuple[int, str]:
    """Resolve TELEGRAM_API_ID / TELEGRAM_API_HASH for --fresh-login.

    Reuses the package's env-var resolution (same variables, same
    validation, RuntimeError on missing/invalid values).
    """
    try:
        from arbling_telegram_mcp.client import get_api_credentials as resolve
    except ImportError:
        raise RuntimeError(
            "arbling-telegram-mcp is not importable in this interpreter. "
            "Install it first (pip install arbling-telegram-mcp) or run this "
            "script with the interpreter where it is installed."
        ) from None
    return resolve()


def fresh_login_session_string() -> str:
    """Interactive Telegram login that mints a BRAND-NEW StringSession.

    Never opens or reads the local session file — the resulting string has
    its own dedicated auth key, so the hosted deployment can never collide
    with the laptop's session (the AuthKeyDuplicatedError failure mode of
    the default conversion path). Requires network access.

    Telethon itself prompts on the terminal for the phone number, login
    code, and — when two-step verification is enabled — the 2FA password.
    The prompts are not wrapped or echoed here.
    """
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id, api_hash = get_api_credentials()

    client = TelegramClient(StringSession(), api_id, api_hash)
    client.start()  # Telethon's own interactive prompts (phone / code / 2FA)
    try:
        session_string = client.session.save()
    finally:
        client.disconnect()

    if not session_string:
        raise RuntimeError(
            "Fresh login finished but produced an empty session string. "
            "Re-run with --fresh-login and complete the login prompts."
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
            "Export a Telethon session to Railway as TELEGRAM_SESSION_STRING: "
            "convert the local session (offline, default) or mint a brand-new "
            "one with --fresh-login. The value is never printed."
        ),
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fresh-login",
        action="store_true",
        help=(
            "interactively log in to Telegram (phone + code + optional 2FA) "
            "to mint a BRAND-NEW session string with its own dedicated auth "
            "key instead of converting the local session file. Requires "
            "network access. Recommended for hosted deployments — avoids the "
            "shared-auth-key AuthKeyDuplicatedError (see epilog)."
        ),
    )
    parser.add_argument("--service", default=None, help="Railway service name")
    parser.add_argument(
        "--environment", default=None, help="Railway environment name"
    )
    args = parser.parse_args(argv)

    try:
        if args.fresh_login:
            session_string = fresh_login_session_string()
        else:
            print(DEFAULT_MODE_WARNING, file=sys.stderr)
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
