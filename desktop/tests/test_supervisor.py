"""Lifecycle, readiness and bootstrap tests never contact model providers."""

import json
import socket
from pathlib import Path

import pytest

from desktop import controller as supervisor
from desktop import health
from desktop.app import BrowserOnReady, icon_image
from desktop.controller import Controller
from desktop.paths import child_environment, prepare


@pytest.fixture
def controller(tmp_path):
    config, port = prepare(tmp_path)
    states = []
    return Controller(tmp_path, config, port, states.append), states


class Process:
    pid = 123456
    stdout = None

    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.terminated = False

    def poll(self):
        return self.exit_code

    def wait(self, timeout=None):
        self.exit_code = 0
        return 0


def test_keys_survive_restart_and_are_not_inside_served_data(tmp_path):
    config, port = prepare(tmp_path)
    original = config.read_bytes()
    assert prepare(tmp_path) == (config, port)
    assert config.read_bytes() == original
    env = child_environment(tmp_path, config, "instance-token")
    assert config.parent == Path(env["DATA_DIR"]).parent
    assert not config.is_relative_to(Path(env["DATA_DIR"]))
    assert Path(env["TALEWEAVER_LOG_DIR"]).is_relative_to(tmp_path / "logs")
    assert not Path(env["TALEWEAVER_LOG_DIR"]).is_relative_to(Path(env["DATA_DIR"]))
    assert env["TALEWEAVER_RELOAD"] == "0"
    assert "instance-token" not in original.decode()


def test_existing_database_without_keys_is_never_rekeyed(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/taleweaver.db").write_bytes(b"existing fixture")
    with pytest.raises(ValueError, match="original encryption keys"):
        prepare(tmp_path)
    assert not (tmp_path / "server.env").exists()


def test_start_is_idempotent_and_never_kills_an_unrelated_server(controller, monkeypatch):
    value, states = controller
    owned = Process()
    calls = []
    monkeypatch.setattr(
        supervisor,
        "start_service",
        lambda root, env: calls.append({"cwd": root, "env": env}) or owned,
    )
    value._start()
    value._start()
    assert len(calls) == 1
    assert calls[0]["env"]["TALEWEAVER_DESKTOP_TOKEN"] == value.token
    assert calls[0]["cwd"] == value.root
    assert states == ["starting"]


def test_occupied_port_does_not_spawn_or_stop_another_server(controller, monkeypatch):
    value, _ = controller
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        port = occupied.getsockname()[1]
        text = value.config.read_text().replace("BACKEND_PORT=8000", f"BACKEND_PORT={port}")
        value.config.write_text(text)
        monkeypatch.setattr(
            supervisor, "start_service", lambda *a, **kw: pytest.fail("must not spawn")
        )
        with pytest.raises(OSError):
            value._start()
        assert value.process is None
        value._stop()
        assert value.state == "stopped"


def test_crash_is_yellow_and_explicit_stop_is_red(controller):
    value, states = controller
    value.process = Process(exit_code=17)
    value._check()
    assert value.state == "error"
    value._stop()
    assert states == ["error", "stopped"]


def test_both_services_must_respond_and_can_recover(controller, monkeypatch):
    value, states = controller
    value.process = Process()
    monkeypatch.setattr(health, "ready", lambda *a: True)
    value._check()
    assert value.state == "running"
    monkeypatch.setattr(health, "ready", lambda *a: False)
    value._check()
    assert value.state == "error"
    monkeypatch.setattr(health, "ready", lambda *a: True)
    value._check()
    assert states == ["running", "error", "running"]


def test_stop_uses_authenticated_local_shutdown(controller, monkeypatch):
    value, _ = controller
    process = Process()
    value.process = process
    calls = []
    monkeypatch.setattr(health, "request", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(value, "_signal", lambda *a, **kw: pytest.fail("graceful stop succeeded"))
    value._stop()
    assert calls == [((value.port, "/_desktop/stop"), {"token": value.token, "method": "POST"})]
    assert process.poll() == 0
    assert value.state == "stopped"


@pytest.mark.parametrize("failure", ["foreign", "missing_index", "missing_asset", "network"])
def test_readiness_rejects_wrong_process_or_broken_frontend(monkeypatch, failure):
    def respond(port, path, **kwargs):
        if failure == "network":
            raise OSError("offline")
        if path == "/_desktop/health":
            return json.dumps(
                {"status": "ok", "instance": "foreign" if failure == "foreign" else "own"}
            ).encode()
        if path == "/":
            return (
                b"{}"
                if failure == "missing_index"
                else b'<div id="app"></div><script src="/assets/app.js"></script>'
            )
        if failure == "missing_asset":
            raise ValueError("404")
        return b"console.log('fixture')"

    monkeypatch.setattr(health, "request", respond)
    assert not health.ready(8000, "own")


def test_readiness_checks_a_bounded_sample_of_large_frontend_asset(monkeypatch):
    calls = []

    def respond(port, path, **kwargs):
        calls.append((path, kwargs))
        if path == "/_desktop/health":
            return b'{"status":"ok","instance":"own"}'
        if path == "/":
            return b'<div id="app"></div><script src="/assets/app.js"></script>'
        return b"/* compiled application */"

    monkeypatch.setattr(health, "request", respond)
    assert health.ready(8000, "own")
    assert calls[-1] == ("/assets/app.js", {"sample": True, "kind": "script"})


def test_status_badges_use_requested_colors(tmp_path):
    from PIL import Image

    logo = tmp_path / "logo.png"
    Image.new("RGB", (100, 100), "black").save(logo)
    assert icon_image(logo, "running").getpixel((52, 52))[:3] == (37, 199, 111)
    assert icon_image(logo, "stopped").getpixel((52, 52))[:3] == (239, 69, 69)
    assert icon_image(logo, "error").getpixel((52, 52))[:3] == (246, 195, 67)


def test_browser_opens_once_and_only_after_both_services_are_ready(controller, monkeypatch):
    value, _ = controller
    calls = []
    monkeypatch.setattr("desktop.app.webbrowser.open", calls.append)
    browser = BrowserOnReady(value)
    for state in ("starting", "error", "stopped"):
        browser.update(state)
    assert calls == []
    for state in ("running", "error", "running"):
        browser.update(state)
    assert calls == [f"http://127.0.0.1:{value.port}"]


def test_service_startup_failure_returns_status_without_a_native_crash_dialog(monkeypatch):
    from desktop import entrypoint, server

    def fail():
        raise RuntimeError("controlled startup failure")

    monkeypatch.setattr("sys.argv", ["TaleWeaver", "--server"])
    monkeypatch.setattr(server, "run", fail)
    assert entrypoint.main() == 1


def test_native_menu_smoke_waits_for_tray_setup_and_never_opens_browser(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace

    from PIL import Image

    from desktop import app

    calls = []

    class Icon:
        def __init__(self, *args):
            self.visible = False

        def run(self, setup):
            calls.append("tray initialized")
            setup(self)

        def stop(self):
            calls.append("tray stopped")

        def update_menu(self):
            calls.append("menu updated")

    class Owner:
        state = "stopped"
        port = 8000
        worker = SimpleNamespace(ident=1, join=lambda **kw: None, is_alive=lambda: False)

        def launch(self):
            calls.append("service started")
            self.changed("running")

        def request(self, action):
            if action == "exit":
                self.exited()

    monkeypatch.setitem(
        sys.modules,
        "pystray",
        SimpleNamespace(
            Icon=Icon,
            Menu=lambda *args: args,
            MenuItem=lambda *args, **kwargs: args,
        ),
    )
    monkeypatch.setattr(
        app.webbrowser, "open", lambda *a: pytest.fail("CI must not open a browser")
    )
    logo = tmp_path / "logo.png"
    Image.new("RGB", (64, 64), "black").save(logo)
    assert app.run(Owner(), logo, tmp_path / "desktop.log", smoke_timeout=5)
    assert calls.index("tray initialized") < calls.index("service started")
    assert "menu updated" in calls


def test_storage_probe_refuses_an_existing_profile_without_touching_it(tmp_path):
    from desktop.storage_probe import verify

    (tmp_path / "data").mkdir()
    database = tmp_path / "data/taleweaver.db"
    database.write_bytes(b"existing user database")
    with pytest.raises(ValueError, match="fresh disposable profile"):
        verify(tmp_path)
    assert database.read_bytes() == b"existing user database"
