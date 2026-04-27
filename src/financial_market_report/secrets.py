from __future__ import annotations

import os
from pathlib import Path


def _default_secret_dirs() -> list[Path]:
    dirs = [Path("/run/secrets")]
    app_secrets_dir = os.environ.get("APP_SECRETS_DIR")
    if app_secrets_dir:
        dirs.append(Path(app_secrets_dir))
    return dirs


def read_secret(name: str, *, required: bool = True) -> str | None:
    """Read a secret from environment variables or Docker-style mounted files."""
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

    if required:
        raise RuntimeError(
            f"Missing required secret '{name}'. Set it as an environment variable "
            "or mount it as a file under /run/secrets."
        )
    return None


def secret_status(names: list[str]) -> dict[str, bool]:
    return {name: read_secret(name, required=False) is not None for name in names}
