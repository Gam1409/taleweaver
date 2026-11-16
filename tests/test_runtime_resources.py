"""The portable contract depends on a port, never a particular HTTP catalog."""

import hashlib
from unittest.mock import AsyncMock

import pytest

from backend.schemas.agent_runtime import CorpusRef
from backend.services.runtime_resources import (
    MAX_CORPUS_BYTES,
    ResourceUnavailableError,
    resolve_corpora,
)


def reference(**changes):
    return CorpusRef.model_validate(
        {"id": "lore", "revision": "r1", "sha256": hashlib.sha256(b"{}").hexdigest(), **changes}
    )


@pytest.mark.asyncio
async def test_installed_resources_do_not_touch_remote_adapter():
    installed = AsyncMock()
    installed.read.return_value = b"{}"
    remote = AsyncMock()
    result = await resolve_corpora([reference()], installed, {"community": remote})
    assert result.contents == {"lore": b"{}"}
    installed.read.assert_awaited_once_with("lore", "r1", max_bytes=MAX_CORPUS_BYTES)
    remote.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_remote_adapter_is_injected_and_revision_is_pinned():
    remote = AsyncMock()
    remote.read.return_value = b"{}"
    result = await resolve_corpora(
        [reference(source="remote", library_id="community")], AsyncMock(), {"community": remote}
    )
    assert result.contents == {"lore": b"{}"}
    remote.read.assert_awaited_once_with("lore", "r1", max_bytes=MAX_CORPUS_BYTES)


@pytest.mark.asyncio
async def test_optional_missing_resource_is_reported_required_blocks():
    remote_ref = reference(source="remote", library_id="missing")
    result = await resolve_corpora([remote_ref], AsyncMock(), {})
    assert result.omitted_optional == ("lore",)
    assert not result.contents
    with pytest.raises(ResourceUnavailableError, match="required"):
        await resolve_corpora([remote_ref.model_copy(update={"required": True})], AsyncMock(), {})


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [b"wrong revision", b"x" * (MAX_CORPUS_BYTES + 1)])
async def test_integrity_and_size_are_checked_before_ingestion(data):
    installed = AsyncMock()
    installed.read.return_value = data
    result = await resolve_corpora([reference()], installed, {})
    assert result.omitted_optional == ("lore",)
    assert not result.contents
