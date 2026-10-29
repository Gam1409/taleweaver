"""Async ComfyUI API client; never sends a global interrupt or retries submission."""

import asyncio
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import Any

import httpx

from backend.engine.visual_progress import report
from backend.utils.path_security import validate_provider_url

MAX_IMAGE_BYTES = 32 * 1024 * 1024
HTTP_TIMEOUT = 30
REQUEST_STAGES = {
    "prompt": "workflow submission",
    "history": "job polling",
    "upload": "reference upload",
    "queue": "queue cleanup",
    "object_info": "model and node discovery",
}


@contextmanager
def _request_errors(stage: str) -> Iterator[None]:
    """Keep transport exception types without logging URLs, credentials or payloads."""
    try:
        yield
    except httpx.RequestError as exc:
        hint = "Check ComfyUI connectivity and server logs."
        if isinstance(exc, httpx.TimeoutException):
            hint = (
                f"The HTTP request timed out (HTTP limit: {HTTP_TIMEOUT}s); "
                "this is separate from the workflow execution limit."
            )
        # Preserve the original subclass and request for callers and queue cleanup.
        exc.args = (f"ComfyUI {stage} failed ({type(exc).__name__}). {hint}",)
        raise


def _error_summary(response: httpx.Response) -> str:
    with suppress(ValueError, AttributeError, TypeError):
        payload = response.json()
        nodes = payload.get("node_errors", {})
        names = [
            f"{key} ({value.get('class_type', 'unknown')})"
            for key, value in nodes.items()
            if isinstance(value, dict)
        ]
        return re.sub(r"[^a-zA-Z0-9_().,: -]", "", ", ".join(names))[:400]
    return ""


class ComfyClient:
    def __init__(self, url: str):
        self.url = validate_provider_url(url).rstrip("/")
        self.http = httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False)

    async def __aenter__(self) -> "ComfyClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.http.aclose()

    async def json(self, method: str, path: str, **kwargs: Any) -> Any:
        stage = REQUEST_STAGES.get(path.strip("/").split("/")[0], "API request")
        with _request_errors(stage):
            response = await self.http.request(method, self.url + path, **kwargs)
        if response.is_error:
            raise ValueError(
                f"ComfyUI {path} returned HTTP {response.status_code}. Rejected nodes: {_error_summary(response) or 'see server logs'}."
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ValueError(
                "ComfyUI returned an invalid JSON response. Check the API URL."
            ) from exc

    async def upload(self, content: bytes) -> str:
        import uuid

        result = await self.json(
            "POST",
            "/upload/image",
            files={"image": (f"taleweaver-{uuid.uuid4().hex}.png", content, "image/png")},
            data={"type": "input", "overwrite": "false"},
        )
        name = result.get("name")
        if not name:
            raise ValueError("ComfyUI did not return an uploaded image name.")
        subfolder = result.get("subfolder", "")
        return f"{subfolder}/{name}" if subfolder else name

    async def execute(self, graph: dict, output_node: str, timeout: int) -> bytes:
        report("submitting")
        result = await self.json("POST", "/prompt", json={"prompt": graph})
        prompt_id = result.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ValueError("ComfyUI did not accept the workflow.")
        try:
            report("waiting")
            output = await self._wait(prompt_id, output_node, timeout)
            report("downloading")
            return await self._download(output)
        except (asyncio.CancelledError, TimeoutError, httpx.TimeoutException):
            # Dequeue only this job. An already running job may continue remotely.
            with suppress(httpx.HTTPError, ValueError):
                await self.json("POST", "/queue", json={"delete": [prompt_id]})
            raise

    async def _wait(self, prompt_id: str, output_node: str, timeout: int) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            history = await self.json("GET", f"/history/{prompt_id}")
            entry = history.get(prompt_id)
            if entry:
                return self._image_output(entry, output_node)
            await asyncio.sleep(1)
        raise TimeoutError("ComfyUI queue/execution timed out; a running remote job may continue.")

    @staticmethod
    def _image_output(entry: dict, output_node: str) -> dict:
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            raise ValueError(
                "ComfyUI execution failed. Check the selected workflow and server logs."
            )
        images = entry.get("outputs", {}).get(output_node, {}).get("images", [])
        if not images:
            raise ValueError("ComfyUI finished without an image at the selected output node.")
        output = images[0]
        if not isinstance(output, dict) or not output.get("filename"):
            raise ValueError("Invalid ComfyUI image output.")
        return output

    async def _download(self, output: dict) -> bytes:
        params = {key: output.get(key, "") for key in ("filename", "subfolder", "type")}
        with _request_errors("image download"):
            return await self._download_bytes(params)

    async def _download_bytes(self, params: dict) -> bytes:
        async with self.http.stream("GET", self.url + "/view", params=params) as response:
            if response.is_error:
                raise ValueError(f"ComfyUI image download returned HTTP {response.status_code}.")
            data = bytearray()
            async for part in response.aiter_bytes():
                data.extend(part)
                if len(data) > MAX_IMAGE_BYTES:
                    raise ValueError("ComfyUI image exceeds 32 MiB.")
        return bytes(data)
