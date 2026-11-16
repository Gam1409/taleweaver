"""Private local service entrypoint, also used by the packaged executable."""

import hmac
import os


def run() -> None:
    from desktop.win_stdio import restore

    restore()
    import uvicorn
    from fastapi import APIRouter, HTTPException, Request

    from backend.core.config import settings
    from backend.main import app

    token = os.environ["TALEWEAVER_DESKTOP_TOKEN"]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=settings.BACKEND_PORT,
            workers=1,
            access_log=False,
            log_level="info",
            loop="asyncio",
        )
    )

    async def status() -> dict[str, str]:
        return {"status": "ok", "instance": token}

    async def stop(request: Request) -> dict[str, str]:
        supplied = request.headers.get("X-TaleWeaver-Instance", "")
        if not hmac.compare_digest(supplied, token):
            raise HTTPException(403, "Invalid local instance.")
        server.should_exit = True
        return {"status": "stopping"}

    private = APIRouter()
    private.add_api_route("/_desktop/health", status, include_in_schema=False)
    private.add_api_route("/_desktop/stop", stop, methods=["POST"], include_in_schema=False)
    # These local control endpoints precede the web application's SPA fallback.
    app.router.routes[0:0] = private.routes
    server.run()
