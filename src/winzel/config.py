"""Configuration: packaged defaults overlaid with the user's config.toml."""

from __future__ import annotations

import os
import tomllib
from importlib import resources
from pathlib import Path


class ConfigError(Exception):
    pass


def default_user_config_path() -> Path:
    base = os.environ.get("APPDATA") or Path.home() / ".config"
    return Path(base) / "winzel" / "config.toml"


def load_default_config() -> dict:
    text = resources.files("winzel").joinpath("default_config.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


def merge(base: dict, override: dict) -> dict:
    """Deep merge: tables are merged key by key; other values are replaced."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(user_path: Path | None = None) -> dict:
    """Defaults + user file (if it exists). Invalid TOML raises ConfigError."""
    config = load_default_config()
    path = user_path if user_path is not None else default_user_config_path()
    if not path.is_file():
        return config
    try:
        user = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"configuração inválida em {path}: {exc}") from exc
    return merge(config, user)


def check_timeout(config: dict, check_id: str, default: float) -> float:
    value = config.get("checks", {}).get(check_id, {}).get("timeout_s", default)
    return float(value)


def use_emoji(config: dict) -> bool:
    return bool(config.get("display", {}).get("emoji", True))


def check_option(config: dict, check_id: str, key: str, default):
    """A check's option from `[checks.<id>]`, or the default."""
    return config.get("checks", {}).get(check_id, {}).get(key, default)
