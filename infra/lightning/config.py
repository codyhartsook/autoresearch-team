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


_REQUIRED_SESSION = {"name", "count", "gpu_type", "command"}


def load_session_config(path: str | Path, base_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load a sessions YAML file.

    Merges provider settings (teamspace, org) from *base_cfg* if not
    present in the session file.

    Parameters
    ----------
    path : str | Path
        Path to a sessions YAML file.
    base_cfg : dict | None
        Optional base configuration (typically from :func:`load_config`)
        used as fallback for ``teamspace`` and ``org``.

    Returns
    -------
    dict
        Merged config dict with a validated ``sessions`` list.
    """
    session_path = Path(path)
    if not session_path.exists():
        raise FileNotFoundError(f"Session file not found: {session_path}")

    with open(session_path) as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}

    # Validate that a sessions list is present
    sessions = cfg.get("sessions")
    if not sessions or not isinstance(sessions, list):
        raise ValueError(f"{session_path}: must contain a 'sessions' list")

    for idx, group in enumerate(sessions):
        missing = _REQUIRED_SESSION - set(group)
        if missing:
            raise ValueError(
                f"{session_path}: sessions[{idx}] missing keys: {missing}"
            )

    # Merge provider settings from base config when absent
    if base_cfg:
        if "teamspace" not in cfg and "teamspace" in base_cfg:
            cfg["teamspace"] = base_cfg["teamspace"]
        if "org" not in cfg and "org" in base_cfg:
            cfg["org"] = base_cfg["org"]
        if "user" not in cfg and "user" in base_cfg:
            cfg["user"] = base_cfg["user"]
        if "launch" not in cfg and "launch" in base_cfg:
            cfg["launch"] = base_cfg["launch"]
        # Also carry over repo settings for setup script env vars
        for key in ("repo_url", "repo_branch", "autoresearch_repo_url"):
            if key not in cfg and key in base_cfg:
                cfg[key] = base_cfg[key]

    # Allow env var to override / supply the Lightning org
    env_org = os.environ.get("LIGHTNING_ORG", "")
    if env_org:
        cfg["org"] = env_org

    if "teamspace" not in cfg:
        raise ValueError(
            f"{session_path}: 'teamspace' must be set in the session file "
            "or in the base config"
        )

    return cfg


def session_specs(cfg: dict[str, Any], only: str | None = None) -> list[dict[str, Any]]:
    """Flatten sessions list into individual Studio specs.

    Each session group ``{name, count, gpu_type, command}`` expands to
    ``count`` specs named ``{name}-0``, ``{name}-1``, etc.

    Parameters
    ----------
    cfg : dict
        Config dict containing a ``sessions`` list (from
        :func:`load_session_config`).
    only : str | None
        If provided, filter to the session group with this name.

    Returns
    -------
    list[dict]
        One dict per individual session with keys: ``name``, ``gpu_type``,
        ``command``, ``group``.
    """
    specs: list[dict[str, Any]] = []
    for group in cfg.get("sessions", []):
        if only and group["name"] != only:
            continue
        for i in range(group["count"]):
            specs.append(
                {
                    "name": f"{group['name']}-{i}",
                    "gpu_type": group["gpu_type"],
                    "command": group["command"].format(i=i),
                    "group": group["name"],
                }
            )
    return specs


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
