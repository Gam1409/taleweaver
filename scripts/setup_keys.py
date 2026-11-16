"""Preserve deployment keys; only bootstrap a confirmed new local database."""

import os
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import set_key
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from backend.core.config import Settings
from backend.utils.path_security import ensure_within_base_dir


def _valid_encryption_key(key: str | None) -> bool:
    if not key:
        return False
    try:
        Fernet(key.encode("utf-8"))
    except ValueError:
        return False
    return True


def _new_local_database(settings: Settings, root: Path) -> bool:
    """Inspect the destination only; never connect to a database during bootstrap."""
    try:
        url = make_url(settings.DATABASE_URL)
    except ArgumentError:
        return False
    if url.get_backend_name() != "sqlite" or url.query:
        return False
    database = url.database
    if not database or database == ":memory:":
        return True
    if database.startswith("file:"):
        return False
    path = Path(database)
    if not path.is_absolute():
        path = root / path
    return not (path.exists() or path.is_symlink())


def prepare(root: Path) -> None:
    """Keep valid effective keys intact, including dotenv syntax and env overrides."""
    env_file = Path(os.environ.get("TALEWEAVER_ENV_FILE", str(root / ".env")))
    if not env_file.is_absolute():
        env_file = root / env_file
    # BaseSettings accepts this runtime option; dataclass typing omits private args.
    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]
    needed = []
    if not _valid_encryption_key(settings.ENCRYPTION_KEY):
        needed.append("ENCRYPTION_KEY")
    if not settings.SECRET_KEY:
        needed.append("SECRET_KEY")
    if not needed:
        return
    environment_names = {name.casefold() for name in os.environ}
    if any(name.casefold() in environment_names for name in needed):
        raise ValueError("Set valid security keys in the process environment before setup.")
    if not _new_local_database(settings, root):
        raise ValueError(
            "Restore the original ENCRYPTION_KEY and SECRET_KEY for the existing or "
            "unverified database. Setup will not replace deployment keys."
        )
    destination = ensure_within_base_dir(str(env_file), str(env_file.parent))
    generators = {
        "ENCRYPTION_KEY": lambda: Fernet.generate_key().decode("utf-8"),
        "SECRET_KEY": lambda: secrets.token_hex(32),
    }
    for name in needed:
        set_key(destination, name, generators[name]())


def main() -> int:
    try:
        prepare(Path.cwd())
    except (ValueError, OSError):
        print(
            "Setup could not configure security keys. Restore the original ENCRYPTION_KEY "
            "and SECRET_KEY for an existing database, or check the environment settings and "
            "database configuration. No migrations were run.",
            file=sys.stderr,
        )
        return 1
    print("[+] Security keys are configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
