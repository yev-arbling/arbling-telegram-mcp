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
# Railway CLI invocation — arg list, no shell, value never echoed
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
    assert argv[:3] == ["railway", "variables", "--set"]
    assert argv[3] == f"TELEGRAM_SESSION_STRING={expected_string}"
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
