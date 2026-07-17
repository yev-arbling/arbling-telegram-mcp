"""Tests for scripts/export_session_to_railway.py: offline conversion + safe CLI call."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "export_session_to_railway.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "export_session_to_railway", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_synthetic_sqlite_session(tmp_path: Path) -> Path:
    """Create an authenticated-looking SQLite session on disk (no network)."""
    from telethon.crypto import AuthKey
    from telethon.sessions import SQLiteSession

    session_path = tmp_path / "session"
    session = SQLiteSession(str(session_path))
    session.set_dc(2, "149.154.167.40", 443)
    session.auth_key = AuthKey(data=b"\x01" * 256)
    session.save()
    session.close()
    assert (tmp_path / "session.session").exists()
    return session_path


# ---------------------------------------------------------------------------
# Offline conversion
# ---------------------------------------------------------------------------


def test_conversion_produces_non_empty_string(tmp_path: Path):
    script = _load_script()
    session_path = _make_synthetic_sqlite_session(tmp_path)

    result = script.convert_session_to_string(session_path)

    assert isinstance(result, str)
    assert len(result) > 0


def test_conversion_round_trips_through_string_session(tmp_path: Path):
    from telethon.sessions import StringSession

    script = _load_script()
    session_path = _make_synthetic_sqlite_session(tmp_path)

    result = script.convert_session_to_string(session_path)

    restored = StringSession(result)
    assert restored.dc_id == 2
    assert restored.auth_key.key == b"\x01" * 256


def test_conversion_missing_file_raises(tmp_path: Path):
    script = _load_script()
    with pytest.raises(RuntimeError, match="No session file"):
        script.convert_session_to_string(tmp_path / "nope")


def test_conversion_unauthenticated_session_raises(tmp_path: Path):
    from telethon.sessions import SQLiteSession

    script = _load_script()
    session_path = tmp_path / "empty"
    session = SQLiteSession(str(session_path))  # no auth_key set
    session.save()
    session.close()

    with pytest.raises(RuntimeError, match="no auth key"):
        script.convert_session_to_string(session_path)


# ---------------------------------------------------------------------------
# Railway CLI invocation — arg list, stdin value, no shell, never echoed
# ---------------------------------------------------------------------------


def test_main_calls_railway_with_arg_list_and_never_prints_value(
    tmp_path: Path, capsys
):
    script = _load_script()
    session_path = _make_synthetic_sqlite_session(tmp_path)
    expected_string = script.convert_session_to_string(session_path)

    run_mock = MagicMock(return_value=MagicMock(returncode=0))
    with (
        patch.dict(os.environ, {"TELEGRAM_SESSION_PATH": str(session_path)}),
        patch.object(script.shutil, "which", return_value="railway"),
        patch.object(script.subprocess, "run", run_mock),
    ):
        exit_code = script.main([])

    assert exit_code == 0
    assert run_mock.call_count == 1

    argv = run_mock.call_args[0][0]
    assert isinstance(argv, list)
    # KEY only on the command line — the value goes over stdin, never argv,
    # so it never appears in `ps`/Task Manager for the life of the process.
    assert argv[:4] == ["railway", "variable", "set", "TELEGRAM_SESSION_STRING"]
    assert "--stdin" in argv
    assert not any(expected_string in part for part in argv)

    # Value passed via the input= kwarg (piped to the child's stdin), not argv.
    assert run_mock.call_args.kwargs.get("input") == expected_string
    # Never through a shell.
    assert run_mock.call_args.kwargs.get("shell", False) is False

    captured = capsys.readouterr()
    assert expected_string not in captured.out
    assert expected_string not in captured.err
    assert str(len(expected_string)) in captured.out  # only the length is reported


def test_main_forwards_service_and_environment_flags(tmp_path: Path):
    script = _load_script()
    session_path = _make_synthetic_sqlite_session(tmp_path)

    run_mock = MagicMock(return_value=MagicMock(returncode=0))
    with (
        patch.dict(os.environ, {"TELEGRAM_SESSION_PATH": str(session_path)}),
        patch.object(script.shutil, "which", return_value="railway"),
        patch.object(script.subprocess, "run", run_mock),
    ):
        exit_code = script.main(
            ["--service", "telegram-mcp", "--environment", "production"]
        )

    assert exit_code == 0
    argv = run_mock.call_args[0][0]
    assert argv[-4:] == ["--service", "telegram-mcp", "--environment", "production"]


def test_main_railway_failure_does_not_leak_value(tmp_path: Path, capsys):
    script = _load_script()
    session_path = _make_synthetic_sqlite_session(tmp_path)
    expected_string = script.convert_session_to_string(session_path)

    failed = MagicMock(returncode=1, stdout="oops", stderr="boom")
    with (
        patch.dict(os.environ, {"TELEGRAM_SESSION_PATH": str(session_path)}),
        patch.object(script.shutil, "which", return_value="railway"),
        patch.object(script.subprocess, "run", MagicMock(return_value=failed)),
    ):
        exit_code = script.main([])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert expected_string not in captured.out
    assert expected_string not in captured.err


def test_main_missing_railway_cli_errors_cleanly(tmp_path: Path, capsys):
    script = _load_script()
    session_path = _make_synthetic_sqlite_session(tmp_path)

    with (
        patch.dict(os.environ, {"TELEGRAM_SESSION_PATH": str(session_path)}),
        patch.object(script.shutil, "which", return_value=None),
    ):
        exit_code = script.main([])

    assert exit_code == 1
    assert "Railway CLI not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --fresh-login: dedicated auth key for hosted deployments
# ---------------------------------------------------------------------------

FRESH_ENV = {
    "TELEGRAM_API_ID": "12345",
    "TELEGRAM_API_HASH": "abcdef1234567890",
}


def _make_mock_fresh_client(session_string: str) -> MagicMock:
    """MagicMock shaped like a logged-in TelegramClient on a StringSession."""
    client = MagicMock()
    client.session.save.return_value = session_string
    return client


def test_fresh_login_never_reads_local_session_file(tmp_path: Path):
    """--fresh-login must never construct SQLiteSession or touch the local file.

    A real, convertible local session exists on disk — if the code path read
    it, conversion would succeed silently. The SQLiteSession constructor is
    replaced with a tripwire so any touch fails loudly.
    """
    script = _load_script()
    session_path = _make_synthetic_sqlite_session(tmp_path)

    fresh_string = "FRESH-" + "x" * 32
    client_mock = _make_mock_fresh_client(fresh_string)
    telegram_client_cls = MagicMock(return_value=client_mock)
    sqlite_session_cls = MagicMock(
        side_effect=AssertionError("SQLiteSession must never be constructed")
    )

    run_mock = MagicMock(return_value=MagicMock(returncode=0))
    with (
        patch.dict(
            os.environ, {**FRESH_ENV, "TELEGRAM_SESSION_PATH": str(session_path)}
        ),
        patch("telethon.TelegramClient", telegram_client_cls),
        patch("telethon.sessions.SQLiteSession", sqlite_session_cls),
        patch.object(script.shutil, "which", return_value="railway"),
        patch.object(script.subprocess, "run", run_mock),
    ):
        exit_code = script.main(["--fresh-login"])

    assert exit_code == 0
    sqlite_session_cls.assert_not_called()

    # The client was built on a brand-new in-memory StringSession — never on
    # the local file path — with the same env-resolved API credentials.
    from telethon.sessions import StringSession

    session_arg, api_id, api_hash = telegram_client_cls.call_args[0]
    assert isinstance(session_arg, StringSession)
    assert api_id == 12345
    assert api_hash == "abcdef1234567890"
    assert client_mock.start.call_count == 1
    assert client_mock.disconnect.call_count == 1


def test_fresh_login_pushes_exact_saved_string_via_stdin(capsys):
    """The string pushed to Railway is exactly session.save()'s return value,
    via the same `railway variable set <KEY> --stdin` mechanics, never argv,
    never echoed."""
    script = _load_script()
    fresh_string = "1FreshStringSessionValue" + "y" * 40

    client_mock = _make_mock_fresh_client(fresh_string)
    run_mock = MagicMock(return_value=MagicMock(returncode=0))
    with (
        patch.dict(os.environ, FRESH_ENV),
        patch("telethon.TelegramClient", MagicMock(return_value=client_mock)),
        patch.object(script.shutil, "which", return_value="railway"),
        patch.object(script.subprocess, "run", run_mock),
    ):
        exit_code = script.main(["--fresh-login"])

    assert exit_code == 0
    assert run_mock.call_count == 1

    argv = run_mock.call_args[0][0]
    assert argv[:4] == ["railway", "variable", "set", "TELEGRAM_SESSION_STRING"]
    assert "--stdin" in argv
    assert not any(fresh_string in part for part in argv)
    # Exactly the saved string, over stdin, never through a shell.
    assert run_mock.call_args.kwargs.get("input") == fresh_string
    assert run_mock.call_args.kwargs.get("shell", False) is False

    captured = capsys.readouterr()
    assert fresh_string not in captured.out
    assert fresh_string not in captured.err
    assert str(len(fresh_string)) in captured.out  # only the length is reported


def test_default_path_unchanged_and_warns_about_shared_auth_key(
    tmp_path: Path, capsys
):
    """No flag: conversion + push behave exactly as before, plus a loud
    shared-auth-key warning recommending --fresh-login."""
    script = _load_script()
    session_path = _make_synthetic_sqlite_session(tmp_path)
    expected_string = script.convert_session_to_string(session_path)

    run_mock = MagicMock(return_value=MagicMock(returncode=0))
    with (
        patch.dict(os.environ, {"TELEGRAM_SESSION_PATH": str(session_path)}),
        patch.object(script.shutil, "which", return_value="railway"),
        patch.object(script.subprocess, "run", run_mock),
    ):
        exit_code = script.main([])

    assert exit_code == 0
    # Behavior unchanged: same converted string, same push mechanics.
    argv = run_mock.call_args[0][0]
    assert argv[:4] == ["railway", "variable", "set", "TELEGRAM_SESSION_STRING"]
    assert "--stdin" in argv
    assert run_mock.call_args.kwargs.get("input") == expected_string

    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "auth key" in captured.err
    assert "AuthKeyDuplicatedError" in captured.err
    assert "--fresh-login" in captured.err
    # The warning never leaks the credential.
    assert expected_string not in captured.err
    assert expected_string not in captured.out
