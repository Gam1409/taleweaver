"""Optional corpus resolution port; transport, cache and credentials belong to adapters."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from backend.schemas.agent_runtime import CorpusRef

MAX_CORPUS_BYTES = 8 * 1024 * 1024


class ResourceUnavailableError(ValueError):
    """An adapter cannot supply the pinned revision with the required integrity."""


class CorpusLibrary(Protocol):
    async def read(self, resource_id: str, revision: str, *, max_bytes: int) -> bytes:
        """Return bounded canonical bytes or raise ResourceUnavailableError; perform no SQL writes."""
        ...


@dataclass(frozen=True)
class ResolvedCorpora:
    contents: Mapping[str, bytes]
    omitted_optional: tuple[str, ...]


async def resolve_corpora(
    references: list[CorpusRef],
    installed: CorpusLibrary,
    remote: Mapping[str, CorpusLibrary],
) -> ResolvedCorpora:
    """Resolve before starting a session; the host commits only a complete required set."""
    contents = {}
    omitted = []
    for reference in references:
        library = installed if reference.source == "installed" else remote.get(reference.library_id)
        try:
            contents[reference.id] = await _read_verified(library, reference)
        except ResourceUnavailableError:
            if reference.required:
                raise ResourceUnavailableError("A required corpus is unavailable.") from None
            omitted.append(reference.id)
    return ResolvedCorpora(contents, tuple(omitted))


async def _read_verified(library: CorpusLibrary | None, reference: CorpusRef) -> bytes:
    if library is None:
        raise ResourceUnavailableError("No configured library adapter.")
    data = await library.read(reference.id, reference.revision, max_bytes=MAX_CORPUS_BYTES)
    if len(data) > MAX_CORPUS_BYTES or hashlib.sha256(data).hexdigest() != reference.sha256:
        raise ResourceUnavailableError("Corpus integrity or size does not match.")
    return data
