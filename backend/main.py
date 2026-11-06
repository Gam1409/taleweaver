import asyncio
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.responses import Response

# Import all models so SQLAlchemy metadata registers them before create_all
import backend.core.startup_logging
import backend.models.adventure_template
import backend.models.avatar
import backend.models.chat
import backend.models.game_session
import backend.models.session_state
import backend.models.user
import backend.models.world_map
from backend.api.routes import (
    adventures,
    auth_api,
    avatars,
    characters,
    config_api,
    data,
    map_api,
    memory_index,
    memory_settings,
    stt_api,
    tts_api,
    users_api,
)
from backend.api.routes.inference_queue import router as inference_queue_router
from backend.api.routes.system_diagnostics import router as diagnostics_router
from backend.core.config import settings
from backend.core.database import run_db_migrations
from backend.core.diagnostic_http import DiagnosticMiddleware, session_diagnostic_context
from backend.core.frontend import install as install_frontend
from backend.core.system_diagnostics import service as diagnostic_service
from backend.utils.static_media import SafeStaticFiles

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manages application startup and shutdown lifecycle."""
    diagnostic_service.initialize()
    from backend.core.database import engine
    from backend.core.diagnostic_db import install_diagnostics

    install_diagnostics(engine)
    # Database schema is managed exclusively by Alembic.
    await asyncio.to_thread(run_db_migrations)

    from backend.core.database import AsyncSessionLocal
    from backend.engine.turn_replay.service import recover_interrupted

    async with AsyncSessionLocal() as recovery_db:
        await recover_interrupted(recovery_db)

    # Auto-import adventures
    from backend.api.routes.adventures.sessions import _cleanup_stale_empty_session_dirs
    from backend.engine.adventure_importer import AdventureTemplateImporter

    async with AsyncSessionLocal() as db:
        # Check if we have any admins in the database
        result = await db.execute(
            select(backend.models.user.User)
            .where(backend.models.user.User.role == "admin")
            .limit(1)
        )
        has_admin = result.scalars().first() is not None

        if not has_admin:
            logger.info("No admin user found. Please use the setup flow or create a root user.")

        # We no longer auto-import adventures here.
        # Default adventures are imported per-user on their first login.
        # Manual drops in DATA_DIR/imports/adventures are still processed for convenience.
        await AdventureTemplateImporter.import_from_directory(
            db,
            os.path.join(settings.DATA_DIR, "imports", "adventures"),
            delete_after=True,
        )

        # Best-effort cleanup for stale empty session directories at startup.
        session_ids_res = await db.execute(select(backend.models.game_session.GameSession.id))
        active_session_ids = {
            sid for sid in session_ids_res.scalars().all() if isinstance(sid, str)
        }
        removed_dirs = _cleanup_stale_empty_session_dirs(
            active_session_ids=active_session_ids,
            max_age_days=max(0, int(getattr(settings, "SESSION_EMPTY_DIR_CLEANUP_DAYS", 7))),
        )
        if removed_dirs:
            logger.info("Startup cleanup removed %s stale empty session directories.", removed_dirs)

    try:
        yield
    finally:
        from backend.engine.living_world.live import shutdown as stop_living_world

        await stop_living_world()
        from backend.engine.npc_journal.worker import shutdown as stop_npc_journal

        await stop_npc_journal()
        from backend.engine.memory_rag.worker import shutdown as stop_memory_rag

        await stop_memory_rag()
        from backend.engine.dynamic_locations.images import shutdown as stop_location_images

        await stop_location_images()
        diagnostic_service.close()


app = FastAPI(
    title="TaleWeaver",
    description="Backend API for the TaleWeaver text-adventure engine.",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    dependencies=[Depends(session_diagnostic_context)],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )
    logger.exception(
        "Unhandled server error processing %s %s: %s", request.method, request.url.path, exc
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error occurred."},
    )


# Security: Allowed hosts
# Configured via ALLOWED_HOSTS in .env; defaults are the hosts listed in core/config.py.
# When running behind nginx (Docker), nginx is the security boundary.
# For a public non-proxied deployment, set ALLOWED_HOSTS=yourdomain.com
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts_list)

# Performance: Gzip compression
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(DiagnosticMiddleware)

# Allow the Vue.js frontend (dev server) to reach the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{settings.FRONTEND_PORT}",
        f"http://127.0.0.1:{settings.FRONTEND_PORT}",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept", "X-Requested-With"],
    expose_headers=["X-Request-ID"],
)


# Security Headers Middleware
@app.middleware("http")
async def add_security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # HSTS: enabled by default; nginx is expected to terminate TLS in production.
    # Disable in dev (when proxy_headers are not TLS-terminated) via
    # setting the ``Strict-Transport-Security`` response header to empty in
    # an upstream proxy, or by setting ``ENABLE_HSTS=false`` here.
    if getattr(settings, "ENABLE_HSTS", True):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Inline scripts stay blocked. Skulpt needs unsafe-eval, while the two CDN
    # origins serve the optional Skulpt/CodeMirror tools. Styles allow inline CSS.
    response.headers.setdefault(
        "Content-Security-Policy",
        (
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "script-src 'self' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "connect-src 'self' ws: wss: https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "object-src 'none'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'"
        ),
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(self), geolocation=(), payment=(), usb=()"
    )
    return response


app.include_router(config_api.router, prefix="/api")
app.include_router(diagnostics_router, prefix="/api")
app.include_router(inference_queue_router, prefix="/api")
app.include_router(memory_settings.router, prefix="/api")
app.include_router(memory_index.router, prefix="/api")
app.include_router(adventures.router, prefix="/api")
app.include_router(avatars.router, prefix="/api")
app.include_router(characters.router, prefix="/api")
app.include_router(data.router, prefix="/api")
app.include_router(map_api.router, prefix="/api")
app.include_router(auth_api.router, prefix="/api")
app.include_router(users_api.router, prefix="/api")
app.include_router(tts_api.router, prefix="/api")
app.include_router(stt_api.router, prefix="/api")


# Ensure storage directories exist
os.makedirs(os.path.join(settings.DATA_DIR, "characters"), exist_ok=True)
os.makedirs(os.path.join(settings.DATA_DIR, "adventures"), exist_ok=True)
os.makedirs(os.path.join(settings.DATA_DIR, "adventures", "library"), exist_ok=True)
os.makedirs(os.path.join(settings.DATA_DIR, "adventures", "sessions"), exist_ok=True)
os.makedirs(os.path.join(settings.DATA_DIR, "logs"), exist_ok=True)
os.makedirs(os.path.join(settings.DATA_DIR, "users"), exist_ok=True)
os.makedirs(os.path.join(settings.DATA_DIR, "audio"), exist_ok=True)
os.makedirs(os.path.join(settings.DATA_DIR, "imports", "adventures"), exist_ok=True)
os.makedirs(os.path.join(settings.DATA_DIR, "presets", "adventures"), exist_ok=True)
os.makedirs("adventures", exist_ok=True)


# Mount the entire DATA_DIR under /data for robustness, with security filters
app.mount("/data", SafeStaticFiles(directory=os.path.abspath(settings.DATA_DIR)), name="data")

# Resolve static directories relative to this file so the app works regardless of CWD
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
BACKEND_ASSETS_DIR = BACKEND_DIR / "static" / "assets"
FRONTEND_DIST_DIR = Path(os.environ.get("TALEWEAVER_FRONTEND_DIR", PROJECT_ROOT / "frontend_dist"))
BACKEND_ASSETS_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    """Returns a simple liveness signal for load-balancer health checks."""
    return {"status": "ok"}


@app.post("/api/ping")
async def ping() -> dict[str, str]:
    return {"message": "pong"}


# API routes, including liveness, must precede the SPA catch-all.

install_frontend(app, FRONTEND_DIST_DIR, BACKEND_ASSETS_DIR)


def start() -> None:
    """Start the TaleWeaver backend server."""
    import uvicorn

    # On Windows, reload mode spawns a watchdog process and can produce noisy
    # KeyboardInterrupt traces on shutdown. Keep reload opt-in for local dev.
    reload_enabled = os.getenv("TALEWEAVER_RELOAD", "0").lower() in {"1", "true", "yes", "on"}
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",  # noqa: S104 — Intentional LAN access; preserve the existing deployment interface.
        port=settings.BACKEND_PORT,
        reload=reload_enabled,
    )


if __name__ == "__main__":
    start()
