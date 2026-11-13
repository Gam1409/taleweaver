"""Unit tests for DATA_DIR fallback behavior in app settings."""

import sqlite3
from pathlib import Path

from sqlalchemy.engine import make_url

from backend.core.config import Settings


def _isolate_environment(monkeypatch):
    """Ambient DATABASE_URL or a developer .env must not leak into these units."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


def test_data_dir_defaults_to_data_when_env_missing(monkeypatch):
    _isolate_environment(monkeypatch)
    monkeypatch.delenv("DATA_DIR", raising=False)

    cfg = Settings()

    assert cfg.DATA_DIR == "data"
    assert cfg.DATABASE_URL == "sqlite+aiosqlite:///./data/taleweaver.db"


def test_data_dir_defaults_to_data_when_env_empty(monkeypatch):
    _isolate_environment(monkeypatch)
    monkeypatch.setenv("DATA_DIR", "")

    cfg = Settings()

    assert cfg.DATA_DIR == "data"
    assert cfg.DATABASE_URL == "sqlite+aiosqlite:///./data/taleweaver.db"


def test_data_dir_uses_explicit_env_value(monkeypatch):
    _isolate_environment(monkeypatch)
    monkeypatch.setenv("DATA_DIR", "custom_store")

    cfg = Settings()

    assert cfg.DATA_DIR == "custom_store"
    assert cfg.DATABASE_URL == "sqlite+aiosqlite:///./custom_store/taleweaver.db"


def test_absolute_data_dir_reads_the_existing_database_from_another_cwd(tmp_path, monkeypatch):
    _isolate_environment(monkeypatch)
    profile = tmp_path / "persistent profile"
    profile.mkdir()
    database = profile / "taleweaver.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE retained_fixture (id INTEGER)")
        connection.execute("INSERT INTO retained_fixture VALUES (1)")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.chdir(checkout)

    cfg = Settings(DATA_DIR=str(profile))
    parsed = make_url(cfg.DATABASE_URL).database

    assert Path(parsed).is_absolute()
    assert Path(parsed) == database
    with sqlite3.connect(parsed) as connection:
        assert connection.execute("SELECT id FROM retained_fixture").fetchone() == (1,)


def test_relative_data_dir_with_spaces_retains_relative_semantics(monkeypatch):
    _isolate_environment(monkeypatch)
    cfg = Settings(DATA_DIR="custom profile")
    assert cfg.DATABASE_URL == "sqlite+aiosqlite:///./custom profile/taleweaver.db"


def test_explicit_database_url_is_not_changed_by_data_dir(tmp_path, monkeypatch):
    _isolate_environment(monkeypatch)
    url = "sqlite+aiosqlite:///./separate.db"
    cfg = Settings(DATA_DIR=str(tmp_path), DATABASE_URL=url)
    assert url == cfg.DATABASE_URL
