"""Console-free packaged entrypoint with a headless release smoke-test mode."""

import argparse
import logging
import logging.handlers
import sys
import time
from pathlib import Path

from filelock import FileLock, Timeout
from platformdirs import user_data_path

from desktop.controller import Controller


def bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def setup_logging(root: Path) -> Path:
    (root / "logs").mkdir(exist_ok=True, mode=0o700)
    path = root / "logs/desktop.log"
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=5_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    return path


def smoke(controller: Controller, timeout: float) -> int:
    controller.launch()
    deadline = time.monotonic() + timeout
    result = 1
    try:
        while time.monotonic() < deadline:
            if controller.state == "running":
                if sys.stdout is not None:
                    print("TaleWeaver desktop smoke test: backend and frontend ready.", flush=True)
                result = 0
                break
            if controller.state == "error":
                break
            time.sleep(0.1)
    finally:
        controller.request("exit")
        controller.worker.join(timeout=18)
    return 1 if controller.worker.is_alive() else result


def main() -> int:
    parser = argparse.ArgumentParser(description="TaleWeaver system tray launcher")
    parser.add_argument("--server", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument(
        "--data-dir", type=Path, default=user_data_path("TaleWeaver", appauthor=False)
    )
    parser.add_argument("--icon", type=Path)
    args = parser.parse_args()
    if args.server:
        from desktop.server import run

        run()
        return 0
    root = args.data_dir.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with FileLock(root / "desktop.lock", timeout=0):
            return run_locked(args, root)
    except Timeout:
        return 2
    except Exception:
        logging.exception("Desktop startup failed. Check server.env and desktop.log.")
        return 1


def run_locked(args: argparse.Namespace, root: Path) -> int:
    log_path = setup_logging(root)
    controller = Controller(root, root / "server.env", 8000, lambda _: None)
    if args.smoke_test:
        return smoke(controller, args.timeout)
    from desktop.app import run

    logo = args.icon or bundle_root() / "desktop/assets/logo.png"
    run(controller, logo, log_path)
    return 0


if __name__ == "__main__":
    # PyInstaller's spawned subprocess bootstrap must run before argument parsing.
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
