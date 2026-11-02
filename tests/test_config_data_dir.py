"""Unit tests for DATA_DIR fallback behavior in app settings."""

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
