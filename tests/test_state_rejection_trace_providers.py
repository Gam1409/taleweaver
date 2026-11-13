"""Existing provider/embedding hooks feed the independent rejection capture flag."""

from types import SimpleNamespace

import httpx
import pytest

from backend.core.llm_diagnostics import retry
from backend.core.system_diagnostics import service
from tests.state_trace_support import event_payloads, isolate_trace_directory, trace_rows


@pytest.fixture(autouse=True)
def isolated_diagnostics(tmp_path, monkeypatch):
    yield from isolate_trace_directory(tmp_path, monkeypatch)


def test_retry_body_is_captured_without_detailed_logging_or_an_extra_request():
    from backend.core.state_rejection_trace import reject, scope

    service.set_enabled(True, state_failure_traces=True)
    response = httpx.Response(
        503,
        text="Neutral provider failure body",
        request=httpx.Request("POST", "https://example.com"),
    )
    error = httpx.HTTPStatusError(
        "Synthetic request failure", request=response.request, response=response
    )
    with scope(operation="provider_retry"):
        retry(SimpleNamespace(provider="custom_openai"), attempt=1, error=error)
        reject("state", "unconfirmed", "The provider did not confirm the state proposal.")
    payload = event_payloads(trace_rows(), "detail.llm.retry")[0]
    assert payload["provider_response"]["body"] == "Neutral provider failure body"
    assert payload["attempt"] == 1
    assert service.detailed_logging is False


async def test_embedding_capture_reuses_the_existing_single_mocked_request(monkeypatch):
    from backend.core.state_rejection_trace import reject, scope
    from backend.engine.memory_rag import embeddings
    from backend.engine.memory_rag.settings import MemoryRagSettings

    service.set_enabled(True, state_failure_traces=True)
    calls = []
    configuration = MemoryRagSettings(
        enabled=True, base_url="https://example.com", model="fixture-embedding"
    )
    monkeypatch.setattr(embeddings, "validate_embedding_url", lambda _: "https://example.com")

    async def post(*args):
        calls.append(args)
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]},
            request=httpx.Request("POST", "https://example.com/v1/embeddings"),
        )

    monkeypatch.setattr(embeddings, "_post", post)
    with scope(operation="embedding_validation"):
        result = await embeddings.embed_with_settings(
            configuration, ["Neutral embedding input"], api_key="synthetic-secret"
        )
        reject("state", "unconfirmed", "The proposed memory update lacks confirmation.")
    assert result == [[0.1, 0.2]]
    assert len(calls) == 1
    assert event_payloads(trace_rows(), "detail.embedding.prepared")[0]["texts"] == [
        "Neutral embedding input"
    ]
    assert event_payloads(trace_rows(), "detail.embedding.http.response")[0]["status_code"] == 200
    assert "synthetic-secret" not in str(trace_rows())
