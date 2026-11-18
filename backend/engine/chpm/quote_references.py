"""Request-local selectors over already permitted exact evidence, never saved state."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from backend.core import text_passages
from backend.engine import turn_controls
from backend.engine.chpm.appraisal_context import Window
from backend.engine.chpm.appraisal_contracts import Reference
from backend.engine.chpm.development_context import Episode
from backend.engine.chpm.development_contracts import EpisodeReference
from backend.engine.chpm.host_state import fingerprint
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.motivation import Catalogue

MAX_FRAGMENT_CHARS = 300


def goal_fragments(goal: str) -> dict[str, str]:
    """Keep short-goal handles while making every longer source excerpt selectable."""
    if not goal.strip():
        return {}
    if len(goal) <= MAX_FRAGMENT_CHARS:
        return {"authored_goal": goal}
    return {
        f"authored_goal_{index}": fragment
        for index, fragment in enumerate(_fragments(goal, split_sentences=False))
    }


@dataclass(frozen=True)
class References:
    observer_id: str
    scope: str
    quotes: Mapping[str, Reference]
    episodes: Mapping[str, EpisodeReference]
    fragments: Mapping[str, Mapping[str, str]]
    identifiers: Mapping[str, tuple[str, ...]]
    request_control: Mapping[str, str]

    def validate(self, scope: str, observer_id: str) -> None:
        if (scope, observer_id) != (self.scope, self.observer_id):
            raise ChpmError("CHPM evidence references belong to another prepared source window.")

    def quote(self, identifier: str) -> dict:
        reference = self.quotes.get(identifier)
        if reference is None:
            raise ChpmError("CHPM evidence reference is unavailable in this visible source window.")
        return reference.model_dump()

    def episode(self, identifier: str) -> dict:
        reference = self.episodes.get(identifier)
        if reference is None:
            raise ChpmError("CHPM episode reference is unavailable in this dated source window.")
        return reference.model_dump()

    def project(self, payload: dict) -> dict:
        context = payload["appraisal_context"]
        visible = [
            {
                **{key: value for key, value in row.items() if key != "text"},
                "fragments": dict(self.fragments[row["source_id"]]),
            }
            for row in context["visible_evidence"]
        ]
        return {
            **payload,
            "reference_scope": self.scope,
            **({"request_control": dict(self.request_control)} if self.request_control else {}),
            "appraisal_context": {**context, "visible_evidence": visible},
        }


def build(
    window: Window,
    catalogue: Catalogue,
    episodes: Mapping[str, Episode],
    *,
    binding: dict | None = None,
) -> References:
    if window.payload["observer_id"] != catalogue.observer_id:
        raise ChpmError("CHPM evidence window and motive catalogue have different observers.")
    quotes: dict[str, Reference] = {}
    fragments: dict[str, Mapping[str, str]] = {}
    for alias, (_, source, text) in window.sources.items():
        if not text or text not in source.text:
            raise ChpmError("CHPM visible evidence differs from its exact source.")
        selected = {}
        for fragment in _fragments(text):
            identifier = f"q{len(quotes)}"
            quotes[identifier] = Reference(source_id=alias, quote=fragment)
            selected[identifier] = fragment
        fragments[alias] = MappingProxyType(selected)
    scope = fingerprint(
        {
            "binding": binding or {},
            "observer": catalogue.observer_id,
            "sources": [
                [alias, record, source.model_dump(), text]
                for alias, (record, source, text) in window.sources.items()
            ],
            "motives": [source.model_dump() for source in catalogue.sources.values()],
            "episodes": [
                [alias, episode.record_id, episode.source.model_dump(), episode.excerpt]
                for alias, episode in episodes.items()
            ],
        }
    )
    return References(
        observer_id=catalogue.observer_id,
        scope=scope,
        quotes=MappingProxyType(quotes),
        episodes=MappingProxyType(
            {
                alias: EpisodeReference(episode_id=alias, quote=episode.excerpt)
                for alias, episode in episodes.items()
            }
        ),
        fragments=MappingProxyType(fragments),
        identifiers=MappingProxyType(
            {
                key: tuple(values)
                for key, values in {
                    **window.identifiers(),
                    **catalogue.identifiers(),
                    "fragment_id": list(quotes),
                    "reference_scope": [scope],
                    "episode_id": list(episodes),
                }.items()
            }
        ),
        request_control=MappingProxyType(
            turn_controls.request_view(turn_controls.Operation.model_validate(binding["control"]))
            if binding and binding.get("control")
            else {}
        ),
    )


def _fragments(text: str, *, split_sentences: bool = True) -> list[str]:
    passages = (
        [passage.text for passage in text_passages.spans(text).values()]
        if split_sentences
        else [text]
    )
    result = [
        piece
        for passage in passages
        for offset in range(0, len(passage), MAX_FRAGMENT_CHARS)
        if (piece := passage[offset : offset + MAX_FRAGMENT_CHARS].strip())
    ]
    if "".join("".join(result).split()) != "".join(text.split()):
        raise ChpmError("CHPM evidence selectors did not preserve the complete visible excerpt.")
    return result
