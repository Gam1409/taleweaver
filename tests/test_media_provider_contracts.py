"""Provider responses retain their payload priority and retry semantics."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.media_engine import MediaEngine


@pytest.mark.parametrize(
    ("message", "expected_kind", "expected_value"),
    [
        (
            SimpleNamespace(
                images=[{"image_url": {"url": "https://img.test/first.png"}}],
                content="https://img.test/second.png",
            ),
            "remote",
            "https://img.test/first.png",
        ),
        (
            SimpleNamespace(
                images=[{"url": "data:image/png;base64,AAAA"}],
                content="https://img.test/ignored.png",
            ),
            "base64",
            "data:image/png;base64,AAAA",
        ),
        (
            SimpleNamespace(
                content=[
                    {"type": "text", "text": "ignore"},
                    {"type": "image_url", "image_url": {"url": "https://img.test/content.png"}},
                ]
            ),
            "remote",
            "https://img.test/content.png",
        ),
        (
            SimpleNamespace(
                content=[
                    {
                        "type": "image_url",
                        "image_url": SimpleNamespace(url="https://img.test/object.png"),
                    }
                ]
            ),
            "remote",
            "https://img.test/object.png",
        ),
        (
            SimpleNamespace(content="Picture: (https://img.test/plain.webp)"),
            "remote",
            "https://img.test/plain.webp",
        ),
        (
            SimpleNamespace(content="Picture: data:image/png;base64,AAAA"),
            "base64",
            "data:image/png;base64,AAAA",
        ),
    ],
)
async def test_openrouter_chat_response_priority(
    monkeypatch, message, expected_kind, expected_value
):
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    monkeypatch.setattr(
        MediaEngine, "_get_litellm", lambda: SimpleNamespace(completion=lambda **kwargs: response)
    )
    remote = AsyncMock(return_value="remote-saved")
    base64 = AsyncMock(return_value="base64-saved")
    monkeypatch.setattr(MediaEngine, "_save_remote_image", remote)
    monkeypatch.setattr(MediaEngine, "_save_b64_image", base64)

    result = await MediaEngine._generate_image_openrouter_chat_fallback(
        "portrait",
        "image-model",
        "test-key",
        "unused",
        provider_options={"image_format": "png", "image_quality": 92},
    )

    chosen, ignored = (remote, base64) if expected_kind == "remote" else (base64, remote)
    assert result == f"{expected_kind}-saved"
    chosen.assert_awaited_once_with(expected_value, "unused", None, "png", 92)
    ignored.assert_not_awaited()


async def test_openrouter_retries_dimensions_then_uses_chat_fallback(monkeypatch):
    calls = []
    responses = iter(
        [
            SimpleNamespace(
                status_code=400, json=lambda: {"error": {"message": "size unsupported"}}, text=""
            ),
            SimpleNamespace(
                status_code=400,
                json=lambda: {"error": {"message": "Use chat/completions"}},
                text="",
            ),
        ]
    )

    def post(_url, **kwargs):
        calls.append(kwargs["json"])
        return next(responses)

    monkeypatch.setattr("backend.engine.media_engine.requests.post", post)
    fallback = AsyncMock(return_value="chat-image")
    monkeypatch.setattr(MediaEngine, "_generate_image_openrouter_chat_fallback", fallback)
    options = {"width": 512, "height": 768}

    result = await MediaEngine._generate_image_openrouter_direct(
        "portrait", "openrouter/image-model", "test-key", "unused", provider_options=options
    )

    assert result == "chat-image"
    assert calls == [
        {"model": "image-model", "prompt": "portrait", "size": "512x768"},
        {"model": "image-model", "prompt": "portrait"},
    ]
    fallback.assert_awaited_once_with(
        prompt="portrait",
        model="openrouter/image-model",
        api_key="test-key",
        target_dir="unused",
        filename=None,
        provider_options=options,
    )


async def test_stable_diffusion_preserves_zero_controls(monkeypatch):
    captured = {}

    def post(_url, **kwargs):
        captured.update(kwargs["json"])
        return SimpleNamespace(status_code=200, json=lambda: {"images": ["AAAA"]})

    monkeypatch.setattr("backend.engine.media_engine.requests.post", post)
    monkeypatch.setattr(MediaEngine, "_save_b64_image", AsyncMock(return_value="saved"))
    result = await MediaEngine._generate_image_stable_diffusion_direct(
        "portrait",
        "default",
        "http://localhost:7860/",
        "unused",
        width=0,
        height=0,
        steps=0,
        cfg_scale=0,
        seed=0,
        negative_prompt="",
    )
    assert result == "saved"
    assert captured == {
        "prompt": "portrait",
        "width": 0,
        "height": 0,
        "steps": 0,
        "cfg_scale": 0,
        "seed": 0,
    }
