from __future__ import annotations

import os
from pathlib import Path

from financial_market_report.config import PROJECT_ROOT


VAULT_BOOTSTRAP_NAMES = {"VAULT_ADDR", "VAULT_TOKEN", "VAULT_SECRET_PATH", "VAULT_NAMESPACE", "VAULT_KV_MOUNT"}
_VAULT_CACHE: dict[str, str] | None = None
_VAULT_ERROR: str | None = None


def _default_secret_dirs() -> list[Path]:
    dirs = [Path("/run/secrets"), PROJECT_ROOT / "secrets"]
    app_secrets_dir = os.environ.get("APP_SECRETS_DIR")
    if app_secrets_dir:
        dirs.append(Path(app_secrets_dir))
    return dirs


def _read_env_or_file(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value

    candidates = [name, name.lower()]
    for secret_dir in _default_secret_dirs():
        for candidate in candidates:
            path = secret_dir / candidate
            if path.exists():
                secret = path.read_text(encoding="utf-8").strip()
                if secret:
                    return secret

    return None


def _read_vault_secret(name: str) -> str | None:
    global _VAULT_CACHE, _VAULT_ERROR

    if name in VAULT_BOOTSTRAP_NAMES:
        return None

    if _VAULT_CACHE is not None:
        return _VAULT_CACHE.get(name)
    if _VAULT_ERROR is not None:
        return None

    try:
        from financial_market_report.vault import read_vault_secrets

        _VAULT_CACHE = read_vault_secrets()
    except Exception as exc:
        _VAULT_CACHE = {}
        _VAULT_ERROR = f"{exc.__class__.__name__}: {exc}"
        return None

    return _VAULT_CACHE.get(name)


def clear_secret_cache() -> None:
    global _VAULT_CACHE, _VAULT_ERROR
    _VAULT_CACHE = None
    _VAULT_ERROR = None


def vault_error() -> str | None:
    return _VAULT_ERROR


def read_secret(name: str, *, required: bool = True) -> str | None:
    """Read a secret from Vault first, then environment variables or mounted files."""
    value = _read_vault_secret(name)
    if value:
        return value

    value = _read_env_or_file(name)
    if value:
        return value

    if required:
        hint = "from Vault, an environment variable, or a mounted file under /run/secrets"
        if _VAULT_ERROR:
            hint += f" (last Vault error: {_VAULT_ERROR})"
        raise RuntimeError(
            f"Missing required secret '{name}'. Provide it {hint}."
        )
    return None


def secret_status(names: list[str]) -> dict[str, bool]:
    return {name: read_secret(name, required=False) is not None for name in names}
