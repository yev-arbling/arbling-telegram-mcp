"""Tests for config.py: YAML loading, validation, filtering, and B64 env source."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from arbling_telegram_mcp.config import (
    REQUIRED_CATEGORIES,
    ConfigError,
    filter_by_category,
    get_all_curated_ids,
    load_curated_groups,
)
from tests.conftest import VALID_YAML


def test_load_valid_yaml(fake_config: Path):
    config = load_curated_groups(fake_config)

    assert "tech_news" in config
    assert len(config["tech_news"]) == 2
    assert config["tech_news"][0]["id"] == -1001234567890
    assert config["tech_news"][0]["name"] == "MCP Developers"
    assert config["tech_news"][0]["category"] == "tech_news"

    assert "investor" in config
    assert len(config["investor"]) == 1

    assert "tech_mentors" in config
    assert len(config["tech_mentors"]) == 1


def test_missing_file_returns_empty_categories(tmp_path: Path):
    config = load_curated_groups(tmp_path / "nonexistent.yaml")
    for cat in REQUIRED_CATEGORIES:
        assert cat in config
        assert config[cat] == []


def test_empty_file_returns_required_categories(tmp_path: Path):
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    config = load_curated_groups(p)
    for cat in REQUIRED_CATEGORIES:
        assert cat in config


def test_malformed_yaml_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("{ this is: [not valid yaml", encoding="utf-8")
    with pytest.raises(ConfigError, match="Malformed YAML"):
        load_curated_groups(p)


def test_non_mapping_root_raises(tmp_path: Path):
    p = tmp_path / "list.yaml"
    p.write_text("- foo\n- bar\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_curated_groups(p)


def test_extra_categories_are_kept(tmp_path: Path):
    p = tmp_path / "extra.yaml"
    p.write_text(
        "tech_news: []\ninvestor: []\ntech_mentors: []\ncustom_cat:\n  - id: -9999\n    name: Extra\n",
        encoding="utf-8",
    )
    config = load_curated_groups(p)
    assert "custom_cat" in config
    assert config["custom_cat"][0]["id"] == -9999


def test_missing_required_category_defaults_to_empty(tmp_path: Path):
    p = tmp_path / "partial.yaml"
    p.write_text("tech_news:\n  - id: -1001\n    name: A\n", encoding="utf-8")
    config = load_curated_groups(p)
    for cat in REQUIRED_CATEGORIES:
        assert cat in config
    assert config["investor"] == []
    assert config["tech_mentors"] == []


def test_entry_missing_id_raises(tmp_path: Path):
    p = tmp_path / "bad_entry.yaml"
    p.write_text("tech_news:\n  - name: MissingId\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="missing required 'id'"):
        load_curated_groups(p)


def test_null_category_becomes_empty(tmp_path: Path):
    p = tmp_path / "null_cat.yaml"
    p.write_text("tech_news: ~\ninvestor: []\ntech_mentors: []\n", encoding="utf-8")
    config = load_curated_groups(p)
    assert config["tech_news"] == []


def test_filter_by_category(fake_config: Path):
    config = load_curated_groups(fake_config)
    filtered = filter_by_category(config, "tech_news")
    assert all(g["category"] == "tech_news" for g in filtered)
    assert len(filtered) == 2


def test_filter_none_returns_all(fake_config: Path):
    config = load_curated_groups(fake_config)
    all_groups = filter_by_category(config, None)
    total = sum(len(v) for v in config.values())
    assert len(all_groups) == total


def test_filter_nonexistent_category_returns_empty(fake_config: Path):
    config = load_curated_groups(fake_config)
    assert filter_by_category(config, "no_such_category") == []


def test_get_all_curated_ids(fake_config: Path):
    config = load_curated_groups(fake_config)
    ids = get_all_curated_ids(config)
    assert -1001234567890 in ids
    assert -1009876543210 in ids
    total = sum(len(v) for v in config.values())
    assert len(ids) == total


# ---------------------------------------------------------------------------
# TELEGRAM_CURATED_GROUPS_B64 — hosted-mode env source
# ---------------------------------------------------------------------------


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_b64_env_loads_groups():
    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_B64": _b64(VALID_YAML)}):
        config = load_curated_groups()

    assert len(config["tech_news"]) == 2
    assert config["tech_news"][0]["id"] == -1001234567890
    assert config["investor"][0]["category"] == "investor"


def test_b64_env_wins_over_file_path(fake_config: Path):
    other_yaml = "tech_news:\n  - id: -42\n    name: FromEnv\n"
    with patch.dict(
        "os.environ",
        {
            "TELEGRAM_CURATED_GROUPS_PATH": str(fake_config),
            "TELEGRAM_CURATED_GROUPS_B64": _b64(other_yaml),
        },
    ):
        config = load_curated_groups()

    assert len(config["tech_news"]) == 1
    assert config["tech_news"][0]["id"] == -42


def test_b64_tolerates_line_wrapped_base64():
    encoded = _b64(VALID_YAML)
    wrapped = "\n".join(encoded[i : i + 20] for i in range(0, len(encoded), 20))
    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_B64": wrapped}):
        config = load_curated_groups()

    assert len(config["tech_news"]) == 2


def test_b64_invalid_base64_raises_config_error():
    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_B64": "!!!not-base64!!!"}):
        with pytest.raises(ConfigError, match="base64"):
            load_curated_groups()


def test_b64_invalid_yaml_raises_without_echoing_content():
    bad_yaml = "{ this is: [not valid yaml"
    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_B64": _b64(bad_yaml)}):
        with pytest.raises(ConfigError, match="Malformed YAML") as excinfo:
            load_curated_groups()

    # The decoded content must not appear in the error message.
    assert "not valid yaml" not in str(excinfo.value)


def test_b64_validation_uses_existing_loader_rules():
    missing_id = "tech_news:\n  - name: MissingId\n"
    with patch.dict("os.environ", {"TELEGRAM_CURATED_GROUPS_B64": _b64(missing_id)}):
        with pytest.raises(ConfigError, match="missing required 'id'"):
            load_curated_groups()


def test_b64_explicit_path_argument_bypasses_env(fake_config: Path):
    with patch.dict(
        "os.environ", {"TELEGRAM_CURATED_GROUPS_B64": _b64("tech_news: []")}
    ):
        config = load_curated_groups(fake_config)

    # Explicit path callers (internal/tests) are unaffected by the env var.
    assert len(config["tech_news"]) == 2
