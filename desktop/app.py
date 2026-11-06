"""Native tray menu; no embedded browser, web runtime or model weights."""

import logging
import threading
import webbrowser
from pathlib import Path

from PIL import Image, ImageDraw

from desktop.controller import Controller
from scripts.desktop_processes import open_log

COLORS = {"running": "#25c76f", "stopped": "#ef4545"}


def icon_image(logo: Path, state: str) -> Image.Image:
    with Image.open(logo) as source:
        image = source.convert("RGBA")
    image.thumbnail((64, 64), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (64, 64))
    canvas.paste(image, ((64 - image.width) // 2, (64 - image.height) // 2))
    ImageDraw.Draw(canvas).ellipse(
        (43, 43, 63, 63), fill=COLORS.get(state, "#f6c343"), outline="#111827", width=2
    )
    return canvas


class BrowserOnReady:
    """Open once after readiness, never on transient health recovery."""

    def __init__(self, controller: Controller) -> None:
        self.controller = controller
        self.opened = False

    def update(self, state: str) -> None:
        if state == "running" and not self.opened:
            self.opened = True
            webbrowser.open(f"http://127.0.0.1:{self.controller.port}")


def run(
    controller: Controller, logo: Path, log_path: Path, *, smoke_timeout: float | None = None
) -> bool:
    # Import only for interactive use: the service and CI smoke test need no display.
    import pystray

    browser = BrowserOnReady(controller)
    became_ready = False

    def changed(state: str) -> None:
        nonlocal became_ready
        tray.icon = icon_image(logo, state)
        tray.title = f"TaleWeaver — {state}"
        tray.update_menu()
        if smoke_timeout is None:
            browser.update(state)
        elif state in {"running", "error"}:
            became_ready = state == "running"
            controller.request("exit")

    def action(name: str):
        return lambda _icon, _item: controller.request(name)

    tray = pystray.Icon(
        "TaleWeaver",
        icon_image(logo, "starting"),
        "TaleWeaver — starting",
        pystray.Menu(
            pystray.MenuItem(
                "Open TaleWeaver",
                lambda: webbrowser.open(f"http://127.0.0.1:{controller.port}"),
                default=True,
            ),
            pystray.MenuItem(
                "Start", action("start"), enabled=lambda _: controller.state in {"stopped", "error"}
            ),
            pystray.MenuItem(
                "Stop", action("stop"), enabled=lambda _: controller.state != "stopped"
            ),
            pystray.MenuItem("Restart", action("restart")),
            pystray.MenuItem("Log", lambda: open_log(log_path)),
            pystray.MenuItem("Exit", action("exit")),
        ),
    )
    controller.changed = changed
    controller.exited = tray.stop

    def setup(icon) -> None:
        icon.visible = True
        controller.launch()

    timer = None
    if smoke_timeout is not None:
        timer = threading.Timer(smoke_timeout, lambda: controller.request("exit"))
        timer.daemon = True
        timer.start()
    shutdown_failed = False
    try:
        tray.run(setup)
    finally:
        if timer is not None:
            timer.cancel()
        if controller.worker.ident is not None:
            controller.request("exit")
            controller.worker.join(timeout=18)
            if controller.worker.is_alive():
                logging.error("Service shutdown did not finish; check the owned backend process.")
                shutdown_failed = True
    return became_ready and not shutdown_failed
