"""Source setup shares the application's dotenv and stable-key contract."""

import secrets

import pytest
from cryptography.fernet import Fernet
from dotenv import dotenv_values


@pytest.fixture
def profile(tmp_path, monkeypatch):
    for key in ("ENCRYPTION_KEY", "SECRET_KEY", "DATA_DIR", "DATABASE_URL", "TALEWEAVER_ENV_FILE"):
        monkeypatch.delenv(key, raising=False)
    from scripts.setup_keys import prepare

    return tmp_path, prepare


def write_environment(root, content):
    path = root / ".env"
    path.write_text(content)
    return path


@pytest.mark.parametrize(
    "declaration",
    [
        'ENCRYPTION_KEY="{key}"\nSECRET_KEY="{secret}"\n',
        "export ENCRYPTION_KEY='{key}'\nexport SECRET_KEY='{secret}'\n",
        "ENCRYPTION_KEY = {key}\nSECRET_KEY = {secret}\n",
        "encryption_key={key}\nsecret_key={secret}\n",
        "SOURCE_KEY={key}\nENCRYPTION_KEY=${SOURCE_KEY}\nSECRET_KEY={secret}\n",
    ],
    ids=["quoted", "export", "spacing", "case_insensitive", "interpolation"],
)
def test_valid_values_are_retained_without_any_key_write(profile, declaration, capsys):
    root, prepare = profile
    key, secret = Fernet.generate_key().decode(), secrets.token_urlsafe(40)
    content = declaration.replace("{key}", key).replace("{secret}", secret)
    path = write_environment(root, content)
    (root / "data").mkdir()
    (root / "data/taleweaver.db").touch()

    prepare(root)

    unchanged = path.read_text() == content
    assert unchanged
    assert capsys.readouterr() == ("", "")


def test_environment_keys_are_not_copied_to_dotenv(profile, monkeypatch):
    root, prepare = profile
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("SECRET_KEY", secrets.token_urlsafe(40))
    path = write_environment(root, "# Keys supplied externally\n")
    (root / "data").mkdir()
    (root / "data/taleweaver.db").touch()
    prepare(root)
    assert path.read_text() == "# Keys supplied externally\n"


@pytest.mark.parametrize(
    "name,value", [("ENCRYPTION_KEY", "invalid"), ("ENCRYPTION_KEY", ""), ("SECRET_KEY", "")]
)
def test_invalid_environment_override_cannot_replace_valid_dotenv_keys(
    profile, monkeypatch, name, value
):
    root, prepare = profile
    content = f"ENCRYPTION_KEY={Fernet.generate_key().decode()}\nSECRET_KEY=valid-signing-fixture\n"
    path = write_environment(root, content)
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="environment"):
        prepare(root)
    unchanged = path.read_text() == content
    assert unchanged


def test_unparseable_database_destination_refuses_bootstrap_without_echoing_it(profile):
    root, prepare = profile
    path = write_environment(
        root, "DATABASE_URL=not-a-database-url\nENCRYPTION_KEY=\nSECRET_KEY=\n"
    )
    with pytest.raises(ValueError, match="Restore"):
        prepare(root)
    assert dotenv_values(path)["ENCRYPTION_KEY"] == ""


@pytest.mark.parametrize(
    "database",
    [
        "sqlite+aiosqlite:///./retained.db",
        "postgresql://localhost/unknown",
        "sqlite:///file:unknown?uri=true",
    ],
)
@pytest.mark.parametrize("key", ["", "invalid", "aaaaaaaaaaaaaaaaaaaaaaaa"])
def test_existing_or_unknown_database_refuses_replacement_before_any_write(profile, database, key):
    root, prepare = profile
    (root / "retained.db").touch()
    content = f'DATABASE_URL="{database}"\nENCRYPTION_KEY={key}\nSECRET_KEY=valid-signing-fixture\n'
    path = write_environment(root, content)
    with pytest.raises(ValueError, match="Restore"):
        prepare(root)
    unchanged = path.read_text() == content
    assert unchanged


def test_existing_database_requires_original_signing_key_too(profile):
    root, prepare = profile
    key = Fernet.generate_key().decode()
    path = write_environment(root, f"ENCRYPTION_KEY={key}\nSECRET_KEY=\n")
    before = path.read_bytes()
    (root / "data").mkdir()
    (root / "data/taleweaver.db").touch()
    with pytest.raises(ValueError, match="Restore"):
        prepare(root)
    unchanged = path.read_bytes() == before
    assert unchanged


@pytest.mark.parametrize("target_exists", [False, True], ids=["dangling", "existing"])
def test_database_symlink_is_protected_even_when_the_target_is_missing(profile, target_exists):
    root, prepare = profile
    target = root / "retained.db"
    if target_exists:
        target.touch()
    (root / "data").mkdir()
    (root / "data/taleweaver.db").symlink_to(target)
    path = write_environment(root, "ENCRYPTION_KEY=\nSECRET_KEY=\n")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Restore"):
        prepare(root)
    assert path.read_bytes() == before
    assert (root / "data/taleweaver.db").is_symlink()


def test_new_profile_only_fills_missing_keys_and_retries_are_stable(profile):
    root, prepare = profile
    key = Fernet.generate_key().decode()
    credential = Fernet(key.encode()).encrypt(b"disposable fixture")
    path = write_environment(
        root, f'# Preserve unrelated settings\nENCRYPTION_KEY="{key}"\nSECRET_KEY=\n'
    )
    prepare(root)
    first = path.read_bytes()
    prepare(root)
    stable = path.read_bytes() == first
    assert stable
    values = dotenv_values(path)
    preserved = values["ENCRYPTION_KEY"] == key
    assert preserved
    assert values["SECRET_KEY"]
    assert Fernet(values["ENCRYPTION_KEY"].encode()).decrypt(credential) == b"disposable fixture"
    assert "# Preserve unrelated settings" in path.read_text()


def test_retry_after_a_write_failure_preserves_the_first_generated_key(profile, monkeypatch):
    from scripts import setup_keys

    root, prepare = profile
    path = write_environment(root, "ENCRYPTION_KEY=\nSECRET_KEY=\n")
    original_write = setup_keys.set_key

    def interrupted_write(destination, name, value):
        if name == "SECRET_KEY":
            raise OSError("Disposable write interruption")
        return original_write(destination, name, value)

    monkeypatch.setattr(setup_keys, "set_key", interrupted_write)
    with pytest.raises(OSError, match="interruption"):
        prepare(root)
    key = dotenv_values(path)["ENCRYPTION_KEY"]
    credential = Fernet(key.encode()).encrypt(b"disposable fixture")
    monkeypatch.setattr(setup_keys, "set_key", original_write)
    prepare(root)
    values = dotenv_values(path)
    preserved = values["ENCRYPTION_KEY"] == key
    assert preserved
    assert values["SECRET_KEY"]
    assert Fernet(values["ENCRYPTION_KEY"].encode()).decrypt(credential) == b"disposable fixture"


def test_selected_external_env_file_uses_its_database_and_preserves_other_env(profile, monkeypatch):
    root, prepare = profile
    selected = root / "configuration/server.env"
    selected.parent.mkdir()
    selected.write_text("ENCRYPTION_KEY=\nSECRET_KEY=\n")
    untouched = write_environment(root, "# Not the selected settings file\n")
    monkeypatch.setenv("TALEWEAVER_ENV_FILE", str(selected))
    prepare(root)
    Fernet(dotenv_values(selected)["ENCRYPTION_KEY"].encode())
    assert untouched.read_text() == "# Not the selected settings file\n"


def test_empty_env_file_override_does_not_use_keys_the_application_ignores(profile, monkeypatch):
    root, prepare = profile
    content = f"ENCRYPTION_KEY={Fernet.generate_key().decode()}\nSECRET_KEY=valid-signing-fixture\n"
    path = write_environment(root, content)
    (root / "data").mkdir()
    (root / "data/taleweaver.db").touch()
    monkeypatch.setenv("TALEWEAVER_ENV_FILE", "")
    with pytest.raises(ValueError, match="Restore"):
        prepare(root)
    unchanged = path.read_text() == content
    assert unchanged


def test_valid_symlinked_env_is_preserved(profile):
    root, prepare = profile
    external = root.parent / (root.name + "-external.env")
    content = (
        f"ENCRYPTION_KEY={Fernet.generate_key().decode()}\nSECRET_KEY=opaque-signing-fixture\n"
    )
    external.write_text(content)
    try:
        (root / ".env").symlink_to(external)
        prepare(root)
        unchanged = external.read_text() == content
        assert unchanged
        assert (root / ".env").is_symlink()
    finally:
        external.unlink()
