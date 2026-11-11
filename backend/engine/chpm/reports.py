"""Carry who learned a claim from whom without turning reports into world truth."""

from dataclasses import dataclass
from itertools import zip_longest
from typing import Any

from sqlalchemy import select

from backend.core.system_diagnostics import service
from backend.engine.chpm.core.contracts import Observe
from backend.engine.chpm.core.history import events
from backend.engine.chpm.host_state import Mind, Source, fingerprint, payload
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.report_contracts import MAX_HOPS, ReportHop, ReportLineage
from backend.models.chat import ChatMessage

MAX_ORIGINS = 4


@dataclass(frozen=True)
class Origin:
    actor_id: str
    record_id: str
    source: Source
    roots: tuple[str, ...]


def catalogue(turn: Any) -> dict[str, Origin]:
    result: dict[str, Origin] = {}
    streams = [
        _origins(actor, turn.minds.get(actor), _priority(turn, actor))
        for actor in sorted(turn.decisions)
    ]
    for group in zip_longest(*streams):
        for origin in group:
            if origin is None:
                continue
            key = "k" + fingerprint({"actor": origin.actor_id, "source": origin.record_id})[:16]
            result[key] = origin
            if len(result) == MAX_ORIGINS:
                return result
    return result


def _priority(turn: Any, actor: str) -> list[str]:
    cited = getattr(turn.decisions[actor], "agent_evidence", [])
    recalled = getattr(turn, "semantic_hits", {}).get(actor, [])
    return [item.record_id for item in [*cited, *recalled]]


def _origins(actor: str, mind: Mind | None, priority: list[str]) -> list[Origin]:
    if mind is None:
        return []
    observations = {event.event_id: event for event in events(mind.snapshot)}
    result = []
    for identifier in dict.fromkeys([*priority, *reversed(observations)]):
        event = observations.get(identifier)
        if event is None or not isinstance(event.payload, Observe):
            continue
        source = mind.sources[event.event_id]
        if source.kind == "host_frame" or source.report and len(source.report.hops) >= MAX_HOPS:
            continue
        result.append(Origin(actor, event.event_id, source, event.payload.root_ids))
        if len(result) == 2:
            break
    return result


def context(turn: Any) -> list[dict]:
    if not getattr(turn, "report_origins_enabled", True):
        return []
    if not getattr(turn, "report_origins", None):
        turn.report_origins = catalogue(turn)
    return [
        {
            "origin_id": key,
            "known_by": origin.actor_id,
            "kind": "reported" if origin.source.reported else "witnessed",
            "text": origin.source.text[:320],
            "excerpted": len(origin.source.text) > 320,
        }
        for key, origin in turn.report_origins.items()
    ]


def disable(turn: Any) -> None:
    turn.report_origins_enabled = False
    turn.report_origins = {}
    service.detail("detail.engine.npc.report_context_deferred", reason="input_budget")


def origin_for(turn: Any, speaker: str, alias: str | None) -> Origin | None:
    if alias is None:
        return None
    origin: Origin | None = getattr(turn, "report_origins", {}).get(alias)
    if origin is None or origin.actor_id != speaker:
        raise ValueError("A report origin must be knowledge owned by its actual speaker.")
    mind = turn.minds.get(speaker)
    if mind is None or mind.sources.get(origin.record_id) != origin.source:
        raise ValueError("The speaker's selected report source is no longer available.")
    return origin


def lineage(turn: Any, observer: str, entry: Any) -> ReportLineage | None:
    verdict = getattr(turn, "verdict", None)
    if verdict is None:
        return None
    heard = next(
        (
            row
            for row in verdict.heard
            if row.speaker_id == entry.speaker_id
            and row.quote == entry.quote
            and observer in {row.actor_id, entry.speaker_id}
            and row.origin_id is not None
        ),
        None,
    )
    if heard is None:
        return None
    origin = origin_for(turn, heard.speaker_id, heard.origin_id)
    if origin is None:
        return None
    parent = origin.source
    hop = ReportHop(
        message_id=parent.message_id,
        revision_id=parent.revision_id,
        content_hash=parent.content_hash,
        role=parent.role,
        observer_id=origin.actor_id,
        speaker_id=parent.speaker_id,
        quote=parent.evidence_quote if parent.reported else None,
    )
    previous = parent.report.hops if parent.report else ()
    return ReportLineage(roots=origin.roots, hops=(*previous, hop))


def dependencies(source: Source) -> set[str]:
    return {hop.message_id for hop in source.report.hops} if source.report else set()


def matches(
    source: Source, messages: dict[str, Any], session_id: str, hashes: dict | None = None
) -> bool:
    if source.report is None:
        return True
    return all(
        _matches(hop, messages.get(hop.message_id), session_id, hashes)
        for hop in source.report.hops
    )


def _matches(hop: ReportHop, row: Any, session_id: str, hashes: dict | None = None) -> bool:
    return bool(
        row is not None
        and row.session_id == session_id
        and row.role == hop.role
        and row.revision_id == hop.revision_id
        and (hashes[row.id] if hashes is not None else digest(row.content)) == hop.content_hash
        and (getattr(row, "npc_journal", None) or {}).get("status") != "incomplete"
        and (hop.quote is None or hop.quote in row.content)
    )


async def validate_commit(manager: Any, turn: Any) -> None:
    candidates = [
        origin_for(turn, row.speaker_id, row.origin_id)
        for row in turn.verdict.heard
        if row.origin_id
    ]
    origins = [origin for origin in candidates if origin is not None]
    if not origins:
        return
    ids = {
        identifier
        for origin in origins
        for identifier in {origin.source.message_id, *dependencies(origin.source)}
    }
    rows = await manager.db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == manager.game_id, ChatMessage.id.in_(ids))
        .execution_options(populate_existing=True)
    )
    messages = {row.id: row for row in rows}
    hashes = {key: digest(row.content) for key, row in messages.items()}
    for origin in origins:
        source = origin.source
        hop = ReportHop(
            message_id=source.message_id,
            revision_id=source.revision_id,
            content_hash=source.content_hash,
            role=source.role,
            observer_id=origin.actor_id,
            speaker_id=source.speaker_id,
            quote=source.evidence_quote if source.reported else None,
        )
        if not _matches(
            hop, messages.get(source.message_id), manager.game_id, hashes
        ) or not matches(source, messages, manager.game_id, hashes):
            raise ValueError(
                "Report provenance changed during narration; no transmitted claim was committed."
            )


def fork_roots(
    minds: dict[str, Mind], message_ids: dict[str, str], session_id: str
) -> dict[str, str]:
    from backend.engine.chpm import recent_scene
    from backend.engine.chpm.host_observations import remap_frame

    result: dict[str, str] = {}
    for mind in minds.values():
        genesis = mind.genesis.model_copy(
            update={"scope": mind.genesis.scope.model_copy(update={"world_id": session_id})}
        )
        for source in mind.sources.values():
            if source.report or not recent_scene.dependencies(source) <= message_ids.keys():
                continue
            changed = remap_frame(
                source.model_copy(update={"message_id": message_ids[source.message_id]}),
                message_ids,
            )
            result.update(
                zip(
                    payload(source, mind.genesis).root_ids,
                    payload(changed, genesis).root_ids,
                    strict=True,
                )
            )
    return result


def remap(source: Source, ids: dict[str, str], roots: dict[str, str], session_id: str) -> Source:
    proof = source.report
    if proof is None:
        return source
    changed = ReportLineage(
        roots=tuple(
            roots.get(root) or fingerprint({"session": session_id, "root": root})
            for root in proof.roots
        ),
        hops=tuple(
            hop.model_copy(update={"message_id": ids[hop.message_id]}) for hop in proof.hops
        ),
    )
    return source.model_copy(update={"report": changed})
