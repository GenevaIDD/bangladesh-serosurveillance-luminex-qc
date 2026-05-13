"""Configuration loader/saver — merges defaults with user YAML overrides."""

import copy
from pathlib import Path

import yaml

from .config import DEFAULTS, RESULTS_DIR_NAME


def get_config_path() -> Path:
    """Path to user config YAML file."""
    return Path.home() / RESULTS_DIR_NAME / "config.yaml"


def _deep_merge(base: dict, overrides: dict) -> dict:
    result = copy.deepcopy(base)
    for key, val in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def load_config() -> dict:
    """Load config: defaults overlaid with user YAML overrides."""
    config = copy.deepcopy(DEFAULTS)
    config_path = get_config_path()
    if config_path.exists():
        try:
            user_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if user_config and isinstance(user_config, dict):
                config = _deep_merge(config, user_config)
        except Exception:
            pass  # If YAML is corrupt, fall back to defaults
    return config


def save_config(config: dict) -> None:
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def reset_config() -> None:
    config_path = get_config_path()
    if config_path.exists():
        config_path.unlink()


def get_antigen_names(config: dict) -> list[str]:
    return [a["name"] for a in config["panel"]["antigens"]]


def get_kit_control_names(config: dict) -> list[str]:
    """Kit-control names. Empty list on Uvira; kept for legacy callers."""
    return [c["name"] for c in config["panel"].get("kit_controls", [])]


def get_excluded_analytes(config: dict) -> list[str]:
    """Analytes that are soft-flagged in the report (kept in data, muted in UI)."""
    return list(config.get("panel", {}).get("excluded_analytes", []))


def get_qc_thresholds(config: dict) -> dict:
    return config["qc_thresholds"]
