"""Observer-scoped RAG and host reads. Nothing is committed until the reply is validated."""

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field

from backend.engine.chpm import host_observations
from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.host_state import Mind, Source, identifier, record
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Observation
from backend.engine.memory_rag.documents import MemoryDocument
from backend.engine.memory_rag.ranking import rank_documents, tokens

MAX_PINNED_CHARS = 6000


@dataclass
class Tools:
    mind: Mind
    observation: Observation
    clothing: dict[str, dict]
    pins: dict[str, tuple[str, Source, str]] = field(default_factory=dict)
    exposed: dict[str, tuple[str, Source]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mind.genesis.scope.world_id != self.observation.session_id:
            raise ChpmError("CHPM tools belong to another session.")

    def execute(self, lookup: Lookup) -> dict:
        if lookup.tool == "search_memory":
            return self.search(lookup.argument)
        if lookup.tool == "read_memory":
            item = self.exposed.get(lookup.argument)
            return self.expose(*item, full=True) if item else {"status": "unavailable_source"}
        if lookup.tool == "inspect_self":
            return self.inspect_self()
        return self.visible_clothing(lookup.argument)

    def search(self, query: str) -> dict:
        available = {
            item.id: (index, self.mind.sources[item.event_id])
            for index, item in enumerate(self.mind.snapshot.evidence)
            if item.event_id in self.mind.sources
            and self.mind.sources[item.event_id].kind in {"speech", "world_event"}
        }
        documents = [
            MemoryDocument(
                id=key,
                user_id="",
                session_id=self.mind.genesis.scope.world_id,
                template_id=None,
                layer="dialogue",
                source_id=key,
                source_hash=source.content_hash,
                npc_id=None,
                scene_id=None,
                text=source.text,
                provenance="observer_source",
                source_message_ids=[source.message_id],
                created_at=f"{index:012d}",
            )
            for key, (index, source) in available.items()
        ]
        ranked = rank_documents(documents, query, set(), "")
        return {
            "status": "ok",
            "mode": "lexical_observer_rag",
            "matches": len(ranked),
            "omitted_matches": max(0, len(ranked) - 2),
            "results": [
                self.expose(doc.id, available[doc.id][1], query=query) for doc in ranked[:2]
            ],
        }

    def expose(self, key: str, source: Source, *, full: bool = False, query: str = "") -> dict:
        match = next(
            (
                m
                for m in re.finditer(r"[^\W_]+", source.text)
                if m.group().casefold() in tokens(query)
            ),
            None,
        )
        start = 0 if full or match is None else max(0, match.start() - 80)
        text = source.text if full else source.text[start : start + 600]
        alias = next(
            (a for a, item in self.pins.items() if item[0] == key), f"a{len(self.pins) + 1}"
        )
        used = sum(len(item[2]) for a, item in self.pins.items() if a != alias)
        if used + len(text) > MAX_PINNED_CHARS:
            return {"status": "evidence_budget_exhausted"}
        # Do not shrink a full source when a later search encounters it again.
        if alias in self.pins and len(self.pins[alias][2]) > len(text):
            text = self.pins[alias][2]
        self.pins[alias] = (key, source, text)
        self.exposed[key] = (key, source)
        return {
            "status": "ok",
            "memory_id": key,
            "source_id": alias,
            "source_message_id": source.message_id,
            "speaker_id": source.speaker_id,
            "kind": "reported" if source.kind == "speech" else "witnessed",
            "current_turn": source.message_id == self.observation.message_id,
            "text": text,
            "excerpted": text != source.text,
        }

    def inspect_self(self) -> dict:
        frames = [
            source
            for source in self.mind.sources.values()
            if source.kind == "host_frame"
            and source.message_id == self.observation.message_id
            and source.facts is not None
        ]
        if not frames:
            return {"status": "unknown"}
        source = frames[-1]
        return self.expose(identifier(source, self.mind.genesis), source, full=True)

    def visible_clothing(self, actor_id: str) -> dict:
        facts = host_observations.previous(self.mind)
        current_frame = any(
            source.kind == "host_frame"
            and source.message_id == self.observation.message_id
            and source.facts == facts
            for source in self.mind.sources.values()
        )
        if (
            not current_frame
            or not facts
            or actor_id not in facts.visible_actor_ids
            or actor_id not in self.clothing
        ):
            return {"status": "unavailable_actor"}
        view = deepcopy(self.clothing[actor_id])
        body = {"observation": "current_visible_clothing", "actor_id": actor_id, **view}
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        while len(text) > 2000 and body["clothing"]:
            body["clothing"].pop()
            body["omitted"] += 1
            text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        if len(text) > 2000:
            return {"status": "view_budget_exhausted"}
        source = Source(
            message_id=self.observation.message_id,
            revision_id=self.observation.revision_id,
            content_hash=self.observation.content_hash,
            role="user",
            speaker_id=self.mind.genesis.scope.observer_id,
            kind="world_event",
            text=text,
        )
        result = self.expose(identifier(source, self.mind.genesis), source, full=True)
        if result["status"] == "ok":
            self.mind = record(self.mind, source, minute=self.observation.minute)
        return result
