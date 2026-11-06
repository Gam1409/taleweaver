"""Build a self-contained desktop directory using the current native interpreter."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logo", type=Path)
    args = parser.parse_args()
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("Build the frontend first: cd frontend && npm ci && npm run build")
    assets = ROOT / "desktop/assets"
    assets.mkdir(exist_ok=True)
    logo = args.logo or ROOT / "docs/branding/visualnovel.png"
    with Image.open(logo) as source:
        image = source.convert("RGBA")
    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (1024, 1024))
    canvas.paste(image, ((1024 - image.width) // 2, (1024 - image.height) // 2))
    canvas.save(assets / "logo.png")
    canvas.save(
        assets / "app.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    canvas.save(assets / "app.icns")
    # Analysis imports some modules. Use disposable keys, never deployment secrets.
    env = {
        **os.environ,
        "SECRET_KEY": "desktop-build-analysis-only-not-a-deployment-key",
        "ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            str(ROOT / "desktop/TaleWeaver.spec"),
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )


if __name__ == "__main__":
    main()
