"""Native tray lifecycle without a display or model server."""

import sys
from types import FunctionType, SimpleNamespace

import pytest
from PIL import Image

from desktop import app


class NotificationUnavailableError(Exception):
    def matches(self, domain, code):
        return domain == "dbus" and code == 2


def hide():
    raise RuntimeError("Notification service is not installed")


notification_hide = FunctionType(
    hide.__code__,
    {"__name__": "pystray._util.notify_dbus", "RuntimeError": NotificationUnavailableError},
)


class Icon:
    def __init__(self, calls, cleanup):
        self.visible = False
        self.calls = calls
        self.cleanup = cleanup

    def run(self, setup):
        self.calls.append("tray initialized")
        setup(self)
        if self.cleanup == "missing_notifications":
            notification_hide()
        if self.cleanup == "unrelated_error":
            raise RuntimeError("unrelated tray error")

    def stop(self):
        self.calls.append("tray stopped")

    def update_menu(self):
        self.calls.append("menu updated")


class Owner:
    state = "stopped"
    port = 8000
    worker = SimpleNamespace(ident=1, join=lambda **kw: None, is_alive=lambda: False)

    def __init__(self, calls):
        self.calls = calls

    def launch(self):
        self.calls.append("service started")
        self.state = "running"
        self.changed("running")

    def request(self, action):
        if action == "exit":
            self.state = "stopped"
            self.exited()


@pytest.mark.parametrize("cleanup", ["normal", "missing_notifications", "unrelated_error"])
def test_native_menu_smoke_waits_for_tray_setup_and_never_opens_browser(
    monkeypatch, tmp_path, cleanup
):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "gi.repository",
        SimpleNamespace(
            GLib=SimpleNamespace(Error=NotificationUnavailableError),
            Gio=SimpleNamespace(
                dbus_error_quark=lambda: "dbus", DBusError=SimpleNamespace(SERVICE_UNKNOWN=2)
            ),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "pystray",
        SimpleNamespace(
            Icon=lambda *args: Icon(calls, cleanup),
            Menu=lambda *args: args,
            MenuItem=lambda *args, **kwargs: args,
        ),
    )
    monkeypatch.setattr(
        app.webbrowser, "open", lambda *a: pytest.fail("CI must not open a browser")
    )
    logo = tmp_path / "logo.png"
    Image.new("RGB", (64, 64), "black").save(logo)
    if cleanup == "unrelated_error":
        with pytest.raises(RuntimeError, match="unrelated tray error"):
            app.run(Owner(calls), logo, tmp_path / "desktop.log", smoke_timeout=5)
        return
    assert app.run(Owner(calls), logo, tmp_path / "desktop.log", smoke_timeout=5)
    assert calls.index("tray initialized") < calls.index("service started")
    assert "menu updated" in calls
