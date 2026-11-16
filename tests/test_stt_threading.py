"""Speech inference and lazy segment decoding must leave the event loop available."""

import asyncio
import io
import threading
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.routes import stt_api
from backend.core import global_settings

pytestmark = pytest.mark.asyncio


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 160)
    return output.getvalue()


@pytest.fixture
def speech_settings(monkeypatch):
    owner = SimpleNamespace(game_settings={"whisper_model": "tiny"})
    monkeypatch.setattr(
        global_settings, "resolve_global_settings_owner", AsyncMock(return_value=owner)
    )


async def test_lazy_inference_keeps_other_authenticated_requests_responsive(
    auth_client, speech_settings, monkeypatch
):
    loop = asyncio.get_running_loop()
    main_thread = threading.get_ident()
    entered = asyncio.Event()
    release = threading.Event()
    phases = {}
    decode = stt_api.decode_wav_to_numpy

    def traced_decode(content):
        phases["decode"] = threading.get_ident()
        return decode(content)

    def segments():
        phases["iteration"] = threading.get_ident()
        loop.call_soon_threadsafe(entered.set)
        if threading.get_ident() != main_thread and not release.wait(timeout=10):
            raise RuntimeError("The test did not release its speech worker.")
        yield SimpleNamespace(text="  A neutral")
        yield SimpleNamespace(text=" spoken action.  ")

    class Model:
        def transcribe(self, _audio):
            phases["transcribe"] = threading.get_ident()
            return segments(), {}

    def model(_name):
        phases["load"] = threading.get_ident()
        return Model()

    monkeypatch.setattr(stt_api, "get_whisper_model", model)
    monkeypatch.setattr(stt_api, "decode_wav_to_numpy", traced_decode)
    request = asyncio.create_task(
        auth_client.post(
            "/api/stt/transcribe", files={"file": ("neutral.wav", wav_bytes(), "audio/wav")}
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        status = await asyncio.wait_for(auth_client.get("/api/stt/status"), timeout=5)
        assert status.status_code == 200
        assert not request.done(), "Inference should still be waiting on its worker gate."
    finally:
        release.set()
        response = await request
    assert response.status_code == 200
    assert response.json() == {"text": "A neutral spoken action."}
    assert set(phases) == {"decode", "load", "transcribe", "iteration"}
    assert all(thread_id != main_thread for thread_id in phases.values())


@pytest.mark.parametrize("failure_stage", ["load", "transcribe", "iteration"])
async def test_worker_errors_keep_the_existing_failure_contract(
    auth_client, speech_settings, monkeypatch, failure_stage
):
    def fail():
        raise RuntimeError("Neutral internal speech failure.")

    def segments():
        yield SimpleNamespace(text="Partial text must not be returned.")
        fail()

    class Model:
        def transcribe(self, _audio):
            if failure_stage == "transcribe":
                fail()
            return segments(), {}

    def model(_name):
        if failure_stage == "load":
            fail()
        return Model()

    monkeypatch.setattr(stt_api, "get_whisper_model", model)
    response = await auth_client.post(
        "/api/stt/transcribe", files={"file": ("neutral.wav", wav_bytes(), "audio/wav")}
    )
    assert response.status_code == 500
    assert response.json() == {
        "detail": "Transcription failed. Check the speech-model settings and server logs."
    }
    assert "Partial text" not in response.text


async def test_cancelling_a_request_keeps_other_requests_available(
    auth_client, speech_settings, monkeypatch
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()

    def segments():
        loop.call_soon_threadsafe(entered.set)
        try:
            if not release.wait(timeout=10):
                raise RuntimeError("The test did not release its speech worker.")
            yield SimpleNamespace(text="A cancelled speech result.")
        finally:
            finished.set()

    model = SimpleNamespace(transcribe=lambda _audio: (segments(), {}))
    monkeypatch.setattr(stt_api, "get_whisper_model", lambda _name: model)
    request = asyncio.create_task(
        auth_client.post(
            "/api/stt/transcribe", files={"file": ("neutral.wav", wav_bytes(), "audio/wav")}
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(request, timeout=5)
        response = await asyncio.wait_for(auth_client.get("/api/stt/status"), timeout=5)
        assert response.status_code == 200
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
