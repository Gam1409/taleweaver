"""Keep writable user state outside the application bundle and public data root."""

import os
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values


def prepare(root: Path) -> tuple[Path, int]:
    """Bootstrap a new installation once, never replacing keys for an existing DB."""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = root / "server.env"
    if not config.exists():
        if (root / "data/taleweaver.db").exists():
            raise ValueError(
                "Existing database has no server.env. Restore its original encryption keys."
            )
        content = (
            f"SECRET_KEY={secrets.token_hex(32)}\n"
            f"ENCRYPTION_KEY={Fernet.generate_key().decode()}\n"
            "BACKEND_PORT=8000\n"
        )
        with os.fdopen(os.open(config, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as output:
            output.write(content)
    values = dotenv_values(config)
    if not values.get("SECRET_KEY") or not values.get("ENCRYPTION_KEY"):
        raise ValueError("server.env must contain the original SECRET_KEY and ENCRYPTION_KEY.")
    Fernet(values["ENCRYPTION_KEY"].encode())
    port = int(values.get("BACKEND_PORT") or "8000")
    if not 1 <= port <= 65535:
        raise ValueError("BACKEND_PORT must be between 1 and 65535.")
    for folder in ("data", "logs", "memory"):
        (root / folder).mkdir(exist_ok=True, mode=0o700)
    return config, port


def child_environment(root: Path, config: Path, token: str) -> dict[str, str]:
    """Override deployment paths without putting keys in command arguments or logs."""
    return {
        **os.environ,
        **{key: value for key, value in dotenv_values(config).items() if value is not None},
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "TALEWEAVER_FRONTEND_DIR": str(
            Path(sys._MEIPASS) / "frontend_dist"
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[1] / "frontend/dist"
        ),
        "TALEWEAVER_ENV_FILE": str(config),
        "DATA_DIR": str(root / "data"),
        "DATABASE_URL": "sqlite+aiosqlite:///" + (root / "data/taleweaver.db").as_posix(),
        "MEMORY_DB_DIR": str(root / "memory"),
        "TALEWEAVER_DESKTOP_TOKEN": token,
        "TALEWEAVER_RELOAD": "0",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "PYTHONUNBUFFERED": "1",
    }
