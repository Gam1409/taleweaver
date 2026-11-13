"""Run a copied installer with real local key parsing and inert external tools."""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o700)


def installer_checkout(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "checkout with spaces"
    root.mkdir()
    for name in (
        "setup.sh",
        "backend/__init__.py",
        "backend/core/__init__.py",
        "backend/core/config.py",
        "backend/utils/__init__.py",
        "backend/utils/path_security.py",
        "scripts/setup_keys.py",
    ):
        source = ROOT / name
        if source.exists():
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    (root / "frontend/node_modules/.bin").mkdir(parents=True)
    (root / "frontend/node_modules/.bin/vite").touch()
    (root / "tools").mkdir()
    executable(
        root / "tools/poetry",
        """#!/bin/sh
if [ "$1" = install ]; then exit "${SETUP_TEST_INSTALL_EXIT:-0}"; fi
if [ "$1" = run ] && [ "$2" = python ]; then
 shift 2
 if [ "$1" = -m ] && [ "$2" = alembic ]; then printf 'migration\\n' >> "$SETUP_TEST_LOG"; exit 0; fi
 if [ "$1" = -c ] && [ "$2" = "import fastapi, uvicorn, sqlalchemy, alembic, cryptography, pydantic_settings, lancedb" ]; then exit 0; fi
 exec "$SETUP_TEST_PYTHON" "$@"
fi
exit 91
""",
    )
    executable(root / "tools/npm", '#!/bin/sh\nprintf "npm\\n" >> "$SETUP_TEST_LOG"\n')
    executable(root / "tools/node", '#!/bin/sh\nprintf "v24.0.0\\n"\n')
    executable(root / "tools/git", "#!/bin/sh\nexit 92\n")
    excluded = {"ENCRYPTION_KEY", "SECRET_KEY", "DATA_DIR", "DATABASE_URL", "TALEWEAVER_ENV_FILE"}
    env = {key: value for key, value in os.environ.items() if key.upper() not in excluded}
    env.update(
        PATH=str(root / "tools") + os.pathsep + env.get("PATH", ""),
        PYTHONPATH=str(root),
        SETUP_TEST_LOG=str(root / "events.log"),
        SETUP_TEST_PYTHON=sys.executable,
    )
    return root, env
