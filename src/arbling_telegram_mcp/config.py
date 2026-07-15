"""YAML curated-groups config: load, validate, and query."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".arbling-telegram-mcp" / "curated-groups.yaml"
REQUIRED_CATEGORIES = ("tech_news", "investor", "tech_mentors")
CURATED_GROUPS_B64_ENV = "TELEGRAM_CURATED_GROUPS_B64"


class ConfigError(Exception):
    pass


def get_config_path() -> Path:
    raw = os.environ.get("TELEGRAM_CURATED_GROUPS_PATH", "")
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_CONFIG_PATH


def load_curated_groups(config_path: Optional[Path] = None) -> dict[str, list[dict]]:
    """
    Load and validate the curated groups config.

    Source precedence (when config_path is not passed explicitly):
    1. TELEGRAM_CURATED_GROUPS_B64 env var — base64-encoded UTF-8 YAML (hosted mode).
    2. YAML file at TELEGRAM_CURATED_GROUPS_PATH or the default path.

    Returns dict[category, list[{id, name, category}]].
    Missing file returns empty required categories rather than raising.
    Malformed YAML raises ConfigError.
    """
    if config_path is None:
        b64_value = os.environ.get(CURATED_GROUPS_B64_ENV, "").strip()
        if b64_value:
            return _load_curated_groups_from_b64(b64_value)
        config_path = get_config_path()

    if not config_path.exists():
        return {cat: [] for cat in REQUIRED_CATEGORIES}

    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Malformed YAML in {config_path}: {exc}")

    return _validate_curated_data(data)


def _load_curated_groups_from_b64(b64_value: str) -> dict[str, list[dict]]:
    """Decode TELEGRAM_CURATED_GROUPS_B64 as base64-encoded UTF-8 YAML.

    Error messages never echo the (decoded or raw) content — the group list
    may name private groups.
    """
    try:
        # Tolerate line wrapping added by encoders like the `base64` CLI.
        compact = "".join(b64_value.split())
        text = base64.b64decode(compact, validate=True).decode("utf-8-sig")
    except Exception:
        raise ConfigError(
            f"{CURATED_GROUPS_B64_ENV} is set but could not be decoded as "
            "base64-encoded UTF-8 (content not shown). Re-encode the curated "
            "groups YAML and set the variable again."
        ) from None

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        raise ConfigError(
            f"Malformed YAML in {CURATED_GROUPS_B64_ENV} (content not shown). "
            "Fix the YAML, re-encode it as base64, and set the variable again."
        ) from None

    return _validate_curated_data(data)


def _validate_curated_data(data: object) -> dict[str, list[dict]]:
    """Validate parsed YAML into dict[category, list[{id, name, category}]]."""
    if data is None:
        return {cat: [] for cat in REQUIRED_CATEGORIES}

    if not isinstance(data, dict):
        raise ConfigError(
            f"Expected a YAML mapping at top level, got {type(data).__name__}"
        )

    result: dict[str, list[dict]] = {}
    for category, groups in data.items():
        category = str(category)
        if groups is None:
            result[category] = []
            continue
        if not isinstance(groups, list):
            raise ConfigError(
                f"Category {category!r} must be a list, got {type(groups).__name__}"
            )
        validated: list[dict] = []
        for i, g in enumerate(groups):
            if not isinstance(g, dict):
                raise ConfigError(
                    f"Entry {i} in category {category!r} must be a mapping"
                )
            if "id" not in g:
                raise ConfigError(
                    f"Entry {i} in category {category!r} is missing required 'id' field"
                )
            validated.append(
                {
                    "id": int(g["id"]),
                    "name": str(g.get("name", f"group_{g['id']}")),
                    "category": category,
                }
            )
        result[category] = validated

    for cat in REQUIRED_CATEGORIES:
        if cat not in result:
            result[cat] = []

    return result


def get_all_curated_ids(config: dict[str, list[dict]]) -> set[int]:
    """Return the set of all curated group IDs across all categories."""
    ids: set[int] = set()
    for groups in config.values():
        for g in groups:
            ids.add(g["id"])
    return ids


def filter_by_category(
    config: dict[str, list[dict]],
    category: Optional[str] = None,
) -> list[dict]:
    """Return flat list of group dicts, optionally filtered to one category."""
    if category is not None:
        return list(config.get(category, []))
    result: list[dict] = []
    for groups in config.values():
        result.extend(groups)
    return result
