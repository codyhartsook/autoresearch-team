"""Config loading, validation, and CLI-override merging for the Lightning fleet."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

# Default config lives alongside this module
_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"

# Fields that must be present after loading
_REQUIRED_TOPLEVEL = {"teamspace", "runners", "reviewer", "shared_storage"}
_REQUIRED_RUNNERS = {"count", "gpu_type", "studio_prefix", "command"}
_REQUIRED_REVIEWER = {"enabled", "gpu_type", "studio_name", "command"}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load config.yaml and return a validated dict.

    Parameters
    ----------
    path : str | Path | None
        Explicit path to a config file.  Falls back to the config.yaml
        shipped next to this module.
    """
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    _validate(cfg, config_path)
    return cfg


def apply_overrides(cfg: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Return a *copy* of *cfg* with CLI overrides merged in.

    Supported overrides:
      runners  (int)  – override runners.count
      gpu      (str)  – override runners.gpu_type
    """
    cfg = copy.deepcopy(cfg)
    if overrides.get("runners") is not None:
        cfg["runners"]["count"] = overrides["runners"]
    if overrides.get("gpu") is not None:
        cfg["runners"]["gpu_type"] = overrides["gpu"]
    return cfg


def _validate(cfg: dict[str, Any], path: Path) -> None:
    """Raise on missing required fields."""
    missing_top = _REQUIRED_TOPLEVEL - set(cfg)
    if missing_top:
        raise ValueError(f"{path}: missing top-level keys: {missing_top}")

    missing_runners = _REQUIRED_RUNNERS - set(cfg.get("runners", {}))
    if missing_runners:
        raise ValueError(f"{path}: runners section missing keys: {missing_runners}")

    missing_reviewer = _REQUIRED_REVIEWER - set(cfg.get("reviewer", {}))
    if missing_reviewer:
        raise ValueError(f"{path}: reviewer section missing keys: {missing_reviewer}")
