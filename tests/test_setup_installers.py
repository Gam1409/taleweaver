"""Dependency refresh must preserve credentials without real installation work."""

import os
import secrets
import sqlite3
import subprocess

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values

from tests.setup_key_support import installer_checkout

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Bash integration is POSIX-specific")


def run_setup(root, env):
    return subprocess.run(
        ["/bin/bash", "setup.sh", "--skip-start"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


@pytest.mark.parametrize(
    "declaration",
    [
        'ENCRYPTION_KEY="{key}"\nSECRET_KEY="{secret}"\n',
        "ENCRYPTION_KEY='{key}'\nSECRET_KEY='{secret}'\n",
        "export ENCRYPTION_KEY={key}\nexport SECRET_KEY={secret}\n",
        "ENCRYPTION_KEY = {key}\nSECRET_KEY = {secret}\n",
        "ENCRYPTION_KEY={key}\nSECRET_KEY={secret}\n",
    ],
    ids=["double_quotes", "single_quotes", "export", "spacing", "unquoted"],
)
def test_refresh_preserves_valid_keys_and_saved_ciphertext(tmp_path, declaration):
    root, env = installer_checkout(tmp_path)
    key, secret = Fernet.generate_key().decode(), secrets.token_urlsafe(40)
    credential = Fernet(key.encode()).encrypt(b"disposable credential fixture")
    (root / "data").mkdir()
    database = root / "data/taleweaver.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE retained_fixture (cipher BLOB)")
        connection.execute("INSERT INTO retained_fixture VALUES (?)", (credential,))
    lines = declaration.format(key=key, secret=secret)
    (root / ".env").write_text('PROJECT_NAME="TaleWeaver"\n' + lines)

    result = run_setup(root, env)

    assert result.returncode == 0
    stored = dotenv_values(root / ".env")
    key_preserved = stored["ENCRYPTION_KEY"] == key
    signing_preserved = stored["SECRET_KEY"] == secret
    assert key_preserved, "Refresh must keep the original encryption key"
    assert signing_preserved, "Refresh must keep any valid nonempty signing key"
    assert (
        Fernet(stored["ENCRYPTION_KEY"].encode()).decrypt(credential)
        == b"disposable credential fixture"
    )
    with sqlite3.connect(database) as connection:
        row_preserved = (
            connection.execute("SELECT cipher FROM retained_fixture").fetchone()[0] == credential
        )
    assert row_preserved
    no_key_output = (
        key not in result.stdout + result.stderr and secret not in result.stdout + result.stderr
    )
    assert no_key_output


@pytest.mark.parametrize("location", ["default", "absolute_data", "explicit_url"])
@pytest.mark.parametrize(
    "key_line",
    ["ENCRYPTION_KEY=", "ENCRYPTION_KEY=invalid", "ENCRYPTION_KEY=aaaaaaaaaaaaaaaaaaaaaaaa"],
)
def test_existing_database_with_missing_or_invalid_key_stops_before_migrations(
    tmp_path, location, key_line
):
    root, env = installer_checkout(tmp_path)
    database = root / "data/taleweaver.db"
    destination = ""
    if location == "absolute_data":
        database = root / "persistent profile/taleweaver.db"
        destination = f'DATA_DIR="{database.parent}"\n'
    if location == "explicit_url":
        database = root / "other database/retained.db"
        destination = f'DATABASE_URL="sqlite+aiosqlite:///{database.as_posix()}"\n'
    database.parent.mkdir(parents=True)
    database.write_bytes(b"disposable existing database; never opened by setup")
    content = (
        'PROJECT_NAME="TaleWeaver"\n'
        + destination
        + key_line
        + "\nSECRET_KEY=valid-opaque-signing-fixture\n"
    )
    env_file = root / ".env"
    env_file.write_text(content)

    result = run_setup(root, env)

    assert result.returncode != 0
    assert "Restore" in result.stderr
    unchanged = env_file.read_text() == content
    assert unchanged, "A blocked refresh must not replace security settings"
    assert not (root / "events.log").exists()
    assert database.read_bytes() == b"disposable existing database; never opened by setup"


def test_new_install_generates_stable_keys_and_dependency_failure_stops_early(tmp_path):
    root, env = installer_checkout(tmp_path)
    (root / ".env").write_text('PROJECT_NAME="TaleWeaver"\nENCRYPTION_KEY=\nSECRET_KEY=\n')
    assert run_setup(root, env).returncode == 0
    first = dotenv_values(root / ".env")
    Fernet(first["ENCRYPTION_KEY"].encode())
    assert first["SECRET_KEY"]
    assert run_setup(root, env).returncode == 0
    stable = first == dotenv_values(root / ".env")
    assert stable
    (root / "events.log").unlink()
    env["SETUP_TEST_INSTALL_EXIT"] = "17"
    assert run_setup(root, env).returncode != 0
    assert not (root / "events.log").exists()
