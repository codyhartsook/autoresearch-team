"""Config loading, validation, and CLI-override merging for the Lightning fleet."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

# Default config lives alongside this module
_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"

# Fields that must be present after loading
_REQUIRED_TOPLEVEL = {"teamspace", "runners", "reviewer"}
_REQUIRED_RUNNERS = {"count", "gpu_type", "studio_prefix", "command"}
_REQUIRED_REVIEWER = {"enabled", "gpu_type", "studio_name", "command"}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load config.yaml and return a validated dict.

    Parameters
    ----------
    path : str | Path | None
        Explicit path to a config file.  Falls back to the config.yaml
        shipped next to this module.

    The ``org`` field can be set via the ``LIGHTNING_ORG`` environment
    variable, which takes precedence over the YAML value.
    """
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    # Allow env var to override / supply the Lightning org
    env_org = os.environ.get("LIGHTNING_ORG", "")
    if env_org:
        cfg["org"] = env_org

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


def studio_kwargs(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    """Build keyword arguments for ``lightning_sdk.Studio()``.

    Returns a dict with ``name``, ``teamspace``, and either ``org`` or
    ``user`` depending on config.  If neither is set, auto-resolves the
    org from the Lightning API.

    The SDK requires exactly one of ``user`` or ``org`` to identify the
    teamspace owner.  Org takes precedence when both are set.
    """
    kwargs: dict[str, Any] = {"name": name, "teamspace": cfg["teamspace"]}

    org = cfg.get("org", "")
    user = cfg.get("user", "")

    if org:
        kwargs["org"] = org
    elif user:
        kwargs["user"] = user
    else:
        # Auto-resolve: try org first (most teamspaces are org-owned),
        # fall back to user.
        resolved_org = _resolve_lightning_org()
        if resolved_org:
            kwargs["org"] = resolved_org
        else:
            resolved_user = _resolve_lightning_username()
            if resolved_user:
                kwargs["user"] = resolved_user

    return kwargs


def _resolve_lightning_org() -> str:
    """Best-effort: get the Lightning AI org name.

    Resolution order:
    1. ``LIGHTNING_ORG`` env var
    2. Lightning API — picks the first org the user belongs to
    """
    env_org = os.environ.get("LIGHTNING_ORG", "")
    if env_org:
        return env_org
    try:
        from lightning_sdk.lightning_cloud.rest_client import LightningClient

        client = LightningClient()
        resp = client.organizations_service_list_organizations()
        if resp and resp.organizations:
            return resp.organizations[0].name or ""
    except Exception:
        pass
    return ""


def _resolve_lightning_username() -> str:
    """Best-effort: get the current Lightning AI username.

    Resolution order:
    1. ``LIGHTNING_USERNAME`` env var
    2. Lightning API (requires valid auth credentials)
    """
    env_user = os.environ.get("LIGHTNING_USERNAME", "")
    if env_user:
        return env_user
    try:
        from lightning_sdk.lightning_cloud.rest_client import LightningClient

        client = LightningClient()
        user = client.auth_service_get_user()
        return user.username or ""
    except Exception:
        return ""
