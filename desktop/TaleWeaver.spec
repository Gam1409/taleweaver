# Build on the target OS: Python and native libraries cannot be cross-compiled here.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
hidden = collect_submodules("backend")
hidden += ["desktop.server", "scripts.desktop_processes"]
hidden += ["greenlet", "aiosqlite", "sqlalchemy.dialects.sqlite.aiosqlite", "sqlalchemy.dialects.sqlite.pysqlite"]
hidden += collect_submodules("passlib.handlers") + collect_submodules("tiktoken_ext")
hidden += ["uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl", "uvicorn.lifespan.on"]
if sys.platform == "linux":
    hidden += ["pystray._appindicator", "pystray._gtk", "gi.repository.Gtk", "gi.repository.AyatanaAppIndicator3"]
elif sys.platform == "darwin":
    hidden += ["pystray._darwin"]
else:
    hidden += ["pystray._win32"]

datas = [
    (str(root / "alembic"), "alembic"),
    (str(root / "alembic.ini"), "."),
    (str(root / "version.json"), "."),
    (str(root / "frontend/dist"), "frontend_dist"),
    (str(root / "backend/static"), "backend/static"),
    (str(root / "adventures"), "adventures"),
    (str(root / "desktop/assets"), "desktop/assets"),
]
datas += collect_data_files("litellm")
for distribution in ("litellm", "lancedb", "faster-whisper", "pystray", "platformdirs"):
    datas += copy_metadata(distribution, recursive=True)

analysis = Analysis(
    [str(root / "desktop/entrypoint.py")], pathex=[str(root)],
    datas=datas, hiddenimports=hidden,
    excludes=["pytest", "IPython", "tkinter", "matplotlib", "torch", "tensorflow"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True,
    name="TaleWeaver", console=False, debug=False, strip=False, upx=False,
    icon=str(root / "desktop/assets/app.ico") if sys.platform == "win32" else None,
)
collection = COLLECT(executable, analysis.binaries, analysis.datas, name="TaleWeaver", strip=False, upx=False)
if sys.platform == "darwin":
    app = BUNDLE(
        collection, name="TaleWeaver.app", icon=str(root / "desktop/assets/app.icns"),
        bundle_identifier="io.github.gam1409.taleweaver",
        info_plist={"LSUIElement": True, "NSHighResolutionCapable": True},
    )
