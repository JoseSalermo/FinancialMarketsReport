from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from financial_market_report.config import PROJECT_ROOT


@dataclass(frozen=True)
class VaultConfig:
    addr: str
    token: str
    secret_path: str
    namespace: str | None = None


def load_vault_config() -> VaultConfig | None:
    addr = _read_bootstrap_value("VAULT_ADDR")
    token = _read_bootstrap_value("VAULT_TOKEN")
    secret_path = _read_bootstrap_value("VAULT_SECRET_PATH") or "secret/data/financial-market-report"
    namespace = _read_bootstrap_value("VAULT_NAMESPACE")

    if not addr or not token:
        return None

    return VaultConfig(addr=addr, token=token, secret_path=secret_path, namespace=namespace)


def _bootstrap_secret_dirs() -> list[Path]:
    dirs = [Path("/run/secrets"), PROJECT_ROOT / "secrets"]
    app_secrets_dir = os.environ.get("APP_SECRETS_DIR")
    if app_secrets_dir:
        dirs.append(Path(app_secrets_dir))
    return dirs


def _read_bootstrap_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value

    for secret_dir in _bootstrap_secret_dirs():
        for candidate in (name, name.lower()):
            path = secret_dir / candidate
            if path.exists():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
    return None


def _parse_kv_v2_path(secret_path: str) -> tuple[str, str]:
    cleaned = secret_path.strip().strip("/")
    if not cleaned:
        raise ValueError("VAULT_SECRET_PATH cannot be empty")

    parts = cleaned.split("/")
    if len(parts) >= 3 and parts[1] == "data":
        return parts[0], "/".join(parts[2:])
    if len(parts) >= 2:
        return parts[0], "/".join(parts[1:])
    return os.environ.get("VAULT_KV_MOUNT", "secret"), parts[0]


def read_vault_secrets(config: VaultConfig | None = None) -> dict[str, str]:
    config = config or load_vault_config()
    if config is None:
        return {}

    try:
        import hvac
    except ImportError as exc:
        raise RuntimeError("Vault support requires the 'hvac' package to be installed") from exc

    mount_point, path = _parse_kv_v2_path(config.secret_path)
    client = hvac.Client(url=config.addr, token=config.token, namespace=config.namespace)
    if not client.is_authenticated():
        raise RuntimeError("Vault authentication failed")

    response = client.secrets.kv.v2.read_secret_version(path=path, mount_point=mount_point)
    data = response.get("data", {}).get("data", {})
    if not isinstance(data, dict):
        raise RuntimeError("Vault secret payload was not a mapping")

    return {str(key): str(value) for key, value in data.items() if value is not None}
