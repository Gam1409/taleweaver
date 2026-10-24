"""Image failures retain their stage and type without repeating requests or leaking payloads."""

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.engine import comfyui_images
from backend.engine.comfyui_client import ComfyClient
from backend.engine.manifest_apply import visuals
from backend.engine.manifest_apply.context import ApplyContext
from tests.test_comfyui import comfy_options, fake_comfy, workflow

__all__ = ["comfy_options", "fake_comfy", "workflow"]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
@pytest.mark.parametrize(
    ("path", "stage"),
    [
        ("/prompt", "workflow submission"),
        ("/history/job-1", "job polling"),
        ("/view", "image download"),
    ],
)
async def test_transport_failure_keeps_stage_type_and_submission_count(
    fake_comfy, workflow, error_type, path, stage
):
    calls = []

    def respond(request):
        calls.append(request)
        if request.url.path == path:
            raise error_type("", request=request)
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "job-1"})
        if request.url.path == "/history/job-1":
            return httpx.Response(
                200, json={"job-1": {"outputs": {"save": {"images": [{"filename": "a.png"}]}}}}
            )
        return httpx.Response(200, json={})

    async with ComfyClient("http://localhost:8188") as client:
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with pytest.raises(error_type, match=stage) as caught:
            await client.execute(workflow["graph"], "save", 600)

    assert caught.value.request.url.path == path
    assert error_type.__name__ in str(caught.value)
    assert len([r for r in calls if r.url.path == "/prompt"]) == 1
    deletions = [json.loads(r.content) for r in calls if r.url.path == "/queue"]
    expected = (
        [{"delete": ["job-1"]}] if error_type is httpx.ReadTimeout and path != "/prompt" else []
    )
    assert deletions == expected
    assert all(r.url.path != "/interrupt" for r in calls)


class BrokenImageStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"partial image"
        raise httpx.ReadTimeout("private prompt and https://secret@example.com/?token=private")


@pytest.mark.asyncio
async def test_download_stream_timeout_is_safe_and_named(fake_comfy):
    async with ComfyClient("http://localhost:8188") as client:
        await client.http.aclose()
        client.http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=BrokenImageStream()))
        )
        with pytest.raises(httpx.ReadTimeout, match="image download") as caught:
            await client._download({"filename": "private-scene.png"})
    message = str(caught.value)
    assert "30s" in message and "separate" in message
    assert all(text not in message for text in ("private", "secret", "example.com"))


@pytest.mark.asyncio
async def test_generation_budget_timeout_has_context(fake_comfy, comfy_options, monkeypatch):
    monkeypatch.setattr(ComfyClient, "execute", AsyncMock(side_effect=TimeoutError()))
    with pytest.raises(TimeoutError, match=r"ComfyUI generation timed out \(limit: 30s\)"):
        await comfyui_images.generate_comfy_image("A harbor", comfy_options, "unused", "unused")
    assert not fake_comfy


@pytest.fixture
def image_context(monkeypatch):
    generator = SimpleNamespace(
        is_image_moderation_error=lambda exc: False,
        _log_image_generation=AsyncMock(),
    )
    monkeypatch.setattr(visuals, "generator_module", lambda: generator)
    monkeypatch.setattr(visuals, "publish_status", AsyncMock())
    return ApplyContext(db=None, template_id="story", manifest={}, user=None, adventure=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError, ValueError])
async def test_manifest_failure_never_logs_an_empty_reason(image_context, caplog, error_type):
    factory = AsyncMock(side_effect=error_type(""))
    with caplog.at_level(logging.WARNING, logger=visuals.__name__):
        result = await visuals.generate_image(
            image_context,
            status="Scene",
            prompt="private scene",
            factory=factory,
            timeout=600,
            failure_label="Scene image generation for story/SCENE_1",
        )
    assert result is None
    assert f"failed ({error_type.__name__}): No error details provided." in caplog.text
    assert "private scene" not in caplog.text
    assert image_context.image_counters == {"attempts": 1, "successes": 0, "moderation": 0}
    factory.assert_awaited_once()


@pytest.mark.asyncio
async def test_manifest_keeps_inner_timeout_details(image_context, caplog):
    factory = AsyncMock(side_effect=TimeoutError("Prompt preparation exceeded its 90s limit"))
    with caplog.at_level(logging.WARNING, logger=visuals.__name__):
        await visuals.generate_image(
            image_context,
            status="Scene",
            prompt="private",
            factory=factory,
            timeout=735,
            failure_label="Scene image generation",
        )
    assert "Prompt preparation exceeded its 90s limit" in caplog.text
    assert "overall image limit: 735s" in caplog.text
    assert "timed out after 735s" not in caplog.text


@pytest.mark.asyncio
async def test_manifest_outer_timeout_still_cancels_generation(image_context, caplog):
    cancelled = asyncio.Event()

    async def slow():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with caplog.at_level(logging.WARNING, logger=visuals.__name__):
        result = await visuals.generate_image(
            image_context,
            status="Scene",
            prompt="private",
            factory=slow,
            timeout=0.01,
            failure_label="Scene image generation",
        )
    assert result is None and cancelled.is_set()
    assert "timed out: TimeoutError" in caplog.text
    assert "overall image limit: 0.01s" in caplog.text
