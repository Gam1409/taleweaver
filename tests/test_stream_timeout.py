import asyncio

import pytest

from backend.core.llm_router import GameMasterLLM


class MockChunk:
    def __init__(self, content: str):
        self.choices = [MockChoice(content)]


class MockChoice:
    def __init__(self, content: str):
        self.delta = MockDelta(content)


class MockDelta:
    def __init__(self, content: str):
        self.content = content


@pytest.mark.asyncio
async def test_stream_timeout_normal_completion() -> None:
    """Test that a healthy stream yields all chunks without interruption."""

    # Arrange
    async def sample_stream():
        for token in ["Hello", " brave", " hero", "!"]:
            await asyncio.sleep(0.01)
            yield MockChunk(token)

    # Act
    collected = []
    async for chunk in GameMasterLLM._with_stream_timeout(
        sample_stream(), initial_timeout=1.0, chunk_timeout=0.2
    ):
        collected.append(chunk.choices[0].delta.content)

    # Assert
    assert "".join(collected) == "Hello brave hero!"


@pytest.mark.asyncio
async def test_stream_timeout_signals_partial_interruption_after_tokens() -> None:
    """A partial timeout remains visible while previously yielded text is retained."""

    # Arrange
    async def stalled_stream():
        yield MockChunk("The ancient gate creaks open.")
        yield MockChunk(" Cold wind rushes past.")
        # Simulates provider keeping socket open indefinitely after finishing generation
        await asyncio.sleep(5.0)
        yield MockChunk("Should not be reached")

    # Act
    collected = []
    with pytest.raises(TimeoutError, match="before completion"):
        async for chunk in GameMasterLLM._with_stream_timeout(
            stalled_stream(), initial_timeout=1.0, chunk_timeout=0.1
        ):
            collected.append(chunk.choices[0].delta.content)

    # Assert
    assert "".join(collected) == "The ancient gate creaks open. Cold wind rushes past."


@pytest.mark.asyncio
async def test_stream_timeout_raises_when_no_content_generated() -> None:
    """Test that an LLM stream stalling before emitting any tokens raises a TimeoutError."""

    # Arrange
    async def unresponsive_stream():
        await asyncio.sleep(5.0)
        yield MockChunk("Never produced")

    # Act & Assert
    with pytest.raises(TimeoutError, match="The AI model did not respond in time"):
        async for _ in GameMasterLLM._with_stream_timeout(
            unresponsive_stream(), initial_timeout=0.1, chunk_timeout=0.05
        ):
            pass


@pytest.mark.asyncio
async def test_stream_timeout_preserves_narrative_on_connection_error() -> None:
    """Test that network connection drops mid-stream preserve all narrative received so far."""

    # Arrange
    async def dropping_stream():
        yield MockChunk("You draw your blade.")
        await asyncio.sleep(0.01)
        raise ConnectionResetError("Remote server closed connection")

    # Act
    collected = []
    with pytest.raises(ConnectionResetError):
        async for chunk in GameMasterLLM._with_stream_timeout(
            dropping_stream(), initial_timeout=1.0, chunk_timeout=0.2
        ):
            collected.append(chunk.choices[0].delta.content)

    # Assert
    assert "".join(collected) == "You draw your blade."


async def test_voice_prefix_is_flushed_before_partial_error():
    async def source():
        yield MockChunk("<sigh> Hello")
        raise ConnectionResetError("disconnected")

    chunks = []
    with pytest.raises(ConnectionResetError):
        async for chunk in GameMasterLLM._clean_stream_voice_tags(source()):
            chunks.append(chunk.choices[0].delta.content)
    assert "".join(chunks) == "<sigh> Hello"


async def test_provider_stop_then_hanging_socket_is_successful():
    async def source():
        yield MockChunk("Hello")
        final = MockChunk("")
        final.choices[0].finish_reason = "stop"
        yield final
        await asyncio.sleep(5)

    chunks = []
    async for chunk in GameMasterLLM._with_stream_timeout(
        source(), initial_timeout=1, chunk_timeout=0.01
    ):
        chunks.append(chunk.choices[0].delta.content)
    assert "".join(chunks) == "Hello"


@pytest.mark.parametrize("provider", ["custom_openai", "ollama"])
async def test_stream_uses_resolved_model_timeout_despite_legacy_globals(monkeypatch, provider):
    from unittest.mock import AsyncMock

    from backend.core.config import settings
    from backend.models.user import User

    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", True)
    monkeypatch.setattr(settings, "STREAM_INITIAL_TIMEOUT", 0.001)
    monkeypatch.setattr(settings, "STREAM_CHUNK_TIMEOUT", 0.001)
    user = User(
        username="stream-timeout",
        llm_settings={
            "complex_model_provider": provider,
            "complex_model": "local-model",
            "complex_ollama_timeout": 600,
            "custom_openai_timeout": 600,
            "custom_openai_url": "http://localhost:5001/v1",
        },
        encrypted_api_keys={},
    )
    router = GameMasterLLM.for_role(user, "complex")
    assert router.request_timeout == 600
    # Scale the configured wait down for a real asynchronous pause test.
    router.request_timeout = 0.2

    async def source():
        await asyncio.sleep(0.02)
        yield MockChunk("Hello, this is the beginning. ")
        await asyncio.sleep(0.02)
        yield MockChunk("And this is the ending.")

    monkeypatch.setattr(
        router, "_acompletion_with_openrouter_fallback", AsyncMock(return_value=source())
    )
    stream = await router.stream_simple_task("sys", "hello", router.model)
    text = "".join([chunk.choices[0].delta.content async for chunk in stream])
    assert text == "Hello, this is the beginning. And this is the ending."
