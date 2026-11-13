"""Safe HTTP error mapping for the private session knowledge surface."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.responses import JSONResponse

from backend.engine.memory_rag.sqlite_busy import is_sqlite_busy
from backend.engine.world_info.access import WorldInfoError
from backend.engine.world_info.capacity import CapacityError
from backend.engine.world_info.jobs import JobConflictError, JobNotFoundError
from backend.engine.world_info.view_records import ViewIntegrityError, ViewNotFoundError


class WorldInfoRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def safe_route(request: Request) -> Response:
            try:
                return await original(request)
            except (
                WorldInfoError,
                JobConflictError,
                JobNotFoundError,
                ViewNotFoundError,
                ViewIntegrityError,
            ) as exc:
                return _domain_error(exc)
            except CapacityError:
                return JSONResponse(
                    {"detail": "Session knowledge storage is full. Remove entries before saving."},
                    status_code=413,
                )
            except (RequestValidationError, ValidationError, ValueError):
                return JSONResponse(
                    {"detail": "Invalid World Info request. Check the file, fields and limits."},
                    status_code=422,
                )
            except IntegrityError:
                return JSONResponse(
                    {"detail": "World Info changed. Reload and retry."}, status_code=409
                )
            except OperationalError as exc:
                if not is_sqlite_busy(exc):
                    raise
                return JSONResponse(
                    {"detail": "World Info is busy. Retry without discarding your draft."},
                    status_code=409,
                )

        return safe_route


def _domain_error(error: Exception) -> JSONResponse:
    if isinstance(error, WorldInfoError):
        status = error.status
    elif isinstance(error, (JobNotFoundError, ViewNotFoundError)):
        status = 404
    else:
        status = 409
    return JSONResponse({"detail": str(error)}, status_code=status)
