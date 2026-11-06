"""A bundled server uses packaged migrations even from a writable user directory."""

from pathlib import Path

from backend.core.database import run_db_migrations


def test_embedded_migrations_do_not_depend_on_working_directory(monkeypatch, tmp_path):
    from alembic import command

    seen = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(command, "upgrade", lambda config, target: seen.append((config, target)))
    run_db_migrations()
    config, target = seen[0]
    assert target == "head"
    assert Path(config.get_main_option("script_location")).is_absolute()
    assert (Path(config.get_main_option("script_location")) / "env.py").is_file()
    assert config.attributes["configure_logger"] is False
