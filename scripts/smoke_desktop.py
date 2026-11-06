"""Run the built service in a disposable profile and report measured peak RSS."""

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, nargs="?")
    parser.add_argument("--source", action="store_true")
    parser.add_argument("--tray", action="store_true")
    parser.add_argument("--storage", action="store_true")
    args = parser.parse_args()
    if args.executable is None and not args.source:
        parser.error("Provide an executable or select --source.")
    peak_launcher, peak_services = 0, 0
    with tempfile.TemporaryDirectory(prefix="taleweaver-desktop-smoke-") as folder:
        command = (
            [sys.executable, "-m", "desktop"] if args.source else [str(args.executable.resolve())]
        )
        child = subprocess.Popen(
            command
            + [
                "--storage-probe"
                if args.storage
                else "--tray-smoke-test"
                if args.tray
                else "--smoke-test",
                "--data-dir",
                folder,
                "--timeout",
                "150",
            ]
        )
        deadline = time.monotonic() + 180
        owner = psutil.Process(child.pid)
        while child.poll() is None and time.monotonic() < deadline:
            try:
                peak_launcher = max(peak_launcher, owner.memory_info().rss)
                peak_services = max(
                    peak_services,
                    sum(item.memory_info().rss for item in owner.children(recursive=True)),
                )
            except psutil.Error:
                # A process can exit between enumeration and the RSS read.
                print("Process exited during one memory sample; continuing.")
            time.sleep(0.1)
        if child.poll() is None:
            for item in owner.children(recursive=True):
                item.kill()
            child.kill()
            child.wait()
        result = {
            "exit_code": child.returncode,
            "mode": "storage" if args.storage else "tray" if args.tray else "headless",
        }
        if args.storage:
            result["storage_probe_peak_rss_mib"] = round(peak_launcher / 1048576, 1)
        else:
            result["launcher_peak_rss_mib"] = round(peak_launcher / 1048576, 1)
            result["services_peak_rss_mib"] = round(peak_services / 1048576, 1)
        print(json.dumps(result))
        if child.returncode != 0:
            log = Path(folder) / "logs/desktop.log"
            if log.is_file():
                print(log.read_text(encoding="utf-8")[-10000:])
            raise SystemExit(child.returncode or 1)


if __name__ == "__main__":
    main()
