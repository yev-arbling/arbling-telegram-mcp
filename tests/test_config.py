"""Tests for config.py: YAML loading, validation, and filtering."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from arbling_telegram_mcp.config import (
    REQUIRED_CATEGORIES,
    ConfigError,
    filter_by_category,
    get_all_curated_ids,
    load_curated_groups,
)


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
