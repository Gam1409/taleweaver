"""Install the browser UI after API routes, with canonical filesystem boundaries."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.utils.path_security import ensure_within_base_dir


def _file(root: Path, relative: str) -> Path | None:
    try:
        path = Path(ensure_within_base_dir(str(root / relative), str(root)))
    except ValueError:
        return None
    return path if path.is_file() else None


def install(app: FastAPI, frontend: Path, assets: Path) -> None:
    """The SPA catch-all must be registered last, including after /health."""
    if not frontend.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/", tags=["Development"])
        async def development() -> dict:
            return {
                "name": "TaleWeaver Backend API",
                "status": "online",
                "docs": "/docs",
                "frontend_dev_url": "http://localhost:5173",
                "message": "Start Vite with 'cd frontend && npm run dev', or build the production frontend.",
            }

        return
    index = _file(frontend, "index.html")
    if index is None:
        raise RuntimeError(
            "The production frontend has no valid index.html. Rebuild the application."
        )

    @app.get("/assets/{path:path}")
    def serve_assets(path: str) -> FileResponse:
        file = _file(assets, path) or _file(frontend / "assets", path)
        if file is None:
            raise HTTPException(404, "Asset not found.")
        return FileResponse(file)

    @app.get("/{catchall:path}", name="frontend_spa")
    def serve_spa(catchall: str) -> FileResponse:
        if catchall == "api" or catchall.startswith("api/"):
            raise HTTPException(404, "API route not found.")
        return FileResponse(_file(frontend, catchall) or index)
