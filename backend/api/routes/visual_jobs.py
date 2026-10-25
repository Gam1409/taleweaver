"""Bounded, owner-scoped visual jobs for the single-process application server.

Jobs do not survive a backend restart. Clients never automatically resubmit a
lost job; the image server may still be executing it.
"""

import asyncio
import copy
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from backend.core import database
from backend.core.auth import get_current_user
from backend.models.user import User

router = APIRouter(prefix="/visual-jobs", tags=["Visual jobs"])
logger = logging.getLogger(__name__)


class VisualJobRequest(BaseModel):
    id: UUID
    operation: Literal["test", "asset", "catalog", "avatar", "session_npc", "session_illustration"]
    template_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    payload: dict[str, Any]


@dataclass
class VisualJob:
    owner: str
    request: VisualJobRequest
    state: str = "queued"
    result: dict | None = None
    message: str = "Waiting to generate an image."
    created: float = field(default_factory=time.monotonic)
    finished: float | None = None
    task: asyncio.Task | None = None

    def public(self) -> dict:
        return {
            "id": str(self.request.id),
            "state": self.state,
            "result": self.result,
            "message": self.message,
        }


_jobs: dict[str, VisualJob] = {}


def _typed_payload(request: VisualJobRequest):
    from backend.api.routes.adventures.assets import RegenerateVisualRequest
    from backend.api.routes.config_api import CatalogGeneratePayload, TestVisionPayload
    from backend.api.routes.users_api import ProfileImageGenerateRequest
    from backend.engine.scene_illustrations import SceneIllustrationRequest
    from backend.engine.session_portraits import SessionPortraitRequest

    schemas = {
        "test": TestVisionPayload,
        "asset": RegenerateVisualRequest,
        "catalog": CatalogGeneratePayload,
        "avatar": ProfileImageGenerateRequest,
        "session_npc": SessionPortraitRequest,
        "session_illustration": SceneIllustrationRequest,
    }
    if request.operation == "asset" and not request.template_id:
        raise HTTPException(422, "An adventure template is required.")
    if request.operation in ("session_npc", "session_illustration") and not request.session_id:
        raise HTTPException(422, "A saved session is required.")
    try:
        return schemas[request.operation].model_validate(request.payload)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid visual job parameters or workflow.") from exc


async def _dispatch(request: VisualJobRequest, user: User, db):
    from backend.api.routes.adventures.assets import regenerate_visual
    from backend.api.routes.config_api import generate_catalog_image, test_vision_connection
    from backend.api.routes.users_api import UserResponse, generate_my_profile_image
    from backend.engine.scene_illustrations import generate_scene_illustration
    from backend.engine.session_portraits import regenerate_session_portrait

    payload = _typed_payload(request)
    if request.operation == "session_illustration":
        return await generate_scene_illustration(request.session_id, payload, db, user)
    if request.operation == "session_npc":
        return await regenerate_session_portrait(request.session_id, payload, db, user)
    if request.operation == "asset":
        return await regenerate_visual(request.template_id, payload, db, user)
    functions = {
        "test": test_vision_connection,
        "catalog": generate_catalog_image,
        "avatar": generate_my_profile_image,
    }
    result = await functions[request.operation](payload=payload, db=db, current_user=user)
    if request.operation == "avatar":
        return UserResponse.model_validate(result, from_attributes=True).model_dump(mode="json")
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


async def _run(job: VisualJob) -> None:
    job.state = "running"
    job.message = "Waiting for the image provider (including its queue)."
    try:
        async with database.AsyncSessionLocal() as db:
            user = await db.get(User, job.owner)
            if not user:
                raise HTTPException(404, "User no longer exists.")
            result = await asyncio.wait_for(_dispatch(job.request, user, db), timeout=4000)
        _complete(job, result)
    except asyncio.CancelledError:
        job.state = "abandoned"
        job.message = "Stopped waiting. A running remote job may continue; queued ComfyUI jobs are removed when possible."
    except HTTPException as exc:
        job.state, job.message = "failed", str(exc.detail)
    except Exception:
        logger.exception("Visual job failed")
        job.state, job.message = (
            "failed",
            "Image generation failed. Check the provider settings and server logs.",
        )
    finally:
        job.finished = time.monotonic()


def _complete(job: VisualJob, result: Any) -> None:
    if not isinstance(result, dict):
        raise ValueError("Invalid visual job result.")
    job.result = result
    if result.get("status") == "error":
        job.state, job.message = "failed", result.get("message", "Image generation failed.")
        return
    job.state, job.message = "succeeded", "Image generation completed."


def _prune() -> None:
    expired = [
        key for key, job in _jobs.items() if job.finished and time.monotonic() - job.finished > 3600
    ]
    for key in expired:
        del _jobs[key]


def _task_finished(job: VisualJob, task: asyncio.Task) -> None:
    if task.cancelled() and job.finished is None:
        job.state = "abandoned"
        job.message = "Stopped before generation started."
        job.finished = time.monotonic()


def _resource(request: VisualJobRequest) -> tuple:
    if request.operation == "session_illustration":
        return (request.operation, request.session_id, request.payload.get("message_id"))
    if request.operation == "session_npc":
        return (request.operation, request.session_id, request.payload.get("target_id"))
    return (
        request.operation,
        request.template_id,
        request.payload.get("target_type"),
        request.payload.get("target_id"),
    )


@router.post("")
async def create_visual_job(payload: VisualJobRequest, user: User = Depends(get_current_user)):
    _prune()
    if (
        payload.operation == "test"
        and payload.payload.get("provider") == "comfyui"
        and user.role != "admin"
    ):
        raise HTTPException(403, "Only administrators can execute workflow drafts.")
    job_id = str(payload.id)
    existing = _jobs.get(job_id)
    if existing:
        if existing.owner != user.id or existing.request != payload:
            raise HTTPException(409, "Job identifier already used.")
        return existing.public()
    _typed_payload(payload)
    active = [job for job in _jobs.values() if job.owner == user.id and job.finished is None]
    if len(active) >= 4 or len(_jobs) >= 256:
        raise HTTPException(429, "Too many image jobs; wait for existing requests to finish.")
    if any(_resource(job.request) == _resource(payload) for job in active):
        raise HTTPException(409, "An image job for this target is already running.")
    job = VisualJob(user.id, copy.deepcopy(payload))
    _jobs[job_id] = job
    job.task = asyncio.create_task(_run(job))
    job.task.add_done_callback(lambda task: _task_finished(job, task))
    return job.public()


def _owned_job(job_id: UUID, user: User) -> VisualJob:
    job = _jobs.get(str(job_id))
    if not job or job.owner != user.id:
        raise HTTPException(
            404,
            "Job unavailable (possibly after a backend restart). Do not automatically resubmit: the provider may still be running.",
        )
    return job


@router.get("/{job_id}")
async def read_visual_job(job_id: UUID, user: User = Depends(get_current_user)):
    return _owned_job(job_id, user).public()


@router.delete("/{job_id}")
async def abandon_visual_job(job_id: UUID, user: User = Depends(get_current_user)):
    job = _owned_job(job_id, user)
    if job.task and job.finished is None:
        job.task.cancel()
    return {"message": "Stop requested. An already running remote task may continue."}
