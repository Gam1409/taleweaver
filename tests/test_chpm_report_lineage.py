"""Reports retain provenance through several NPCs without spreading world truth."""

import json
from types import SimpleNamespace

import pytest

from backend.engine.chpm import appraisal_context, host_adapter, host_sources, memory, reports
from backend.engine.chpm.host_state import Source, record
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.lifecycle import fork
from backend.engine.chpm.schema import HeardSpeech, KernelState, Verdict
from backend.engine.chpm.state import KEY
from tests.test_chpm_host_state import mind


def message(identifier, content):
    return SimpleNamespace(
        id=identifier,
        content=content,
        session_id="session",
        scene_id="HALL",
        revision_id=None,
        role="assistant",
        npc_journal={},
    )


def relay(sender, receiver, sender_mind, identifier, text):
    turn = SimpleNamespace(
        minds={sender: sender_mind, receiver: mind(receiver)},
        decisions={sender: object(), receiver: object()},
        report_origins={},
    )
    reports.context(turn)
    key = next(key for key, origin in turn.report_origins.items() if origin.actor_id == sender)
    reply = message(identifier, text)
    turn.verdict = Verdict(
        matches=True,
        heard=[HeardSpeech(actor_id=receiver, speaker_id=sender, quote=text, origin_id=key)],
    )
    entry = memory.from_source(reply, receiver, sender, text, "heard_speech")
    return host_adapter.finish(turn, reply, [entry], receiver, minute=10), reply, turn


def chain():
    original = message("origin", "The cardinal removed the vase. PRIVATE_REASON")
    witness = Source(
        message_id=original.id,
        content_hash=digest(original.content),
        role="assistant",
        speaker_id="CARDINAL",
        kind="world_event",
        text=original.content,
    )
    cardinal = record(mind("CARDINAL"), witness, minute=1)
    messenger, first, _ = relay(
        "CARDINAL", "MESSENGER", cardinal, "report-1", "The cardinal says the vase was removed."
    )
    secretary, second, _ = relay(
        "MESSENGER",
        "SECRETARY",
        messenger,
        "report-2",
        "The messenger reports that the cardinal removed the vase.",
    )
    king, third, turn = relay(
        "SECRETARY",
        "KING",
        secretary,
        "report-3",
        "The secretary passed on the report about the removed vase.",
    )
    return (
        {"CARDINAL": cardinal, "MESSENGER": messenger, "SECRETARY": secretary, "KING": king},
        [original, first, second, third],
        turn,
    )


def test_three_relays_keep_the_same_root_and_each_transmission_without_inventing_beliefs():
    minds, rows, _ = chain()
    roots = minds["CARDINAL"].snapshot.evidence[0].root_ids
    for actor, hops in [("MESSENGER", 1), ("SECRETARY", 2), ("KING", 3)]:
        child = minds[actor]
        source = next(iter(child.sources.values()))
        assert source.reported and len(source.report.hops) == hops
        assert child.snapshot.evidence[0].root_ids == roots
        assert not child.snapshot.beliefs and not child.snapshot.experiences
        assert host_sources.from_messages(child, {row.id: row for row in rows}) == child
    view = appraisal_context.build(minds["KING"]).payload
    assert "PRIVATE_REASON" not in json.dumps(view)
    assert next(iter(minds["KING"].sources.values())).speaker_id == "SECRETARY"


def test_changed_original_source_invalidates_all_downstream_reports_but_not_identity():
    minds, rows, _ = chain()
    rows[0].content = "The original source was edited."
    for actor in ("MESSENGER", "SECRETARY", "KING"):
        changed = host_sources.from_messages(minds[actor], {row.id: row for row in rows})
        assert not changed.sources and changed.genesis == minds[actor].genesis


def test_copy_rebinds_every_hop_and_preserves_shared_root_identity():
    minds, rows, _ = chain()
    ids = {row.id: "copied-" + row.id for row in rows}
    copied = KernelState.model_validate(
        fork({KEY: KernelState(minds=minds).model_dump()}, ids, "copy")[KEY]
    )
    expected_roots = copied.minds["CARDINAL"].snapshot.evidence[0].root_ids
    for actor in ("MESSENGER", "SECRETARY", "KING"):
        source = next(iter(copied.minds[actor].sources.values()))
        assert copied.minds[actor].snapshot.evidence[0].root_ids == expected_roots
        assert source.message_id.startswith("copied-")
        assert all(hop.message_id.startswith("copied-") for hop in source.report.hops)
    missing = {key: value for key, value in ids.items() if key != "origin"}
    partial = KernelState.model_validate(
        fork({KEY: KernelState(minds=minds).model_dump()}, missing, "partial")[KEY]
    )
    assert all(not partial.minds[actor].sources for actor in minds)


def test_a_speaker_cannot_cite_another_characters_private_source():
    _, _, turn = chain()
    key = next(iter(turn.report_origins))
    with pytest.raises(ValueError, match="actual speaker"):
        reports.origin_for(turn, "KING", key)


def test_semantic_documents_depend_on_every_report_hop_and_keep_the_origins_private():
    from backend.engine.chpm import semantic_sources

    minds, rows, _ = chain()
    episodes = semantic_sources.episodes(
        minds["KING"], "owner", None, {row.id: row for row in rows}
    )
    assert len(episodes) == 1
    doc = episodes[0].document
    assert set(doc.source_message_ids) == {row.id for row in rows}
    assert doc.provenance == "reported" and "PRIVATE_REASON" not in doc.text
    rows[0].content = "An edited source."
    assert not semantic_sources.episodes(
        minds["KING"], "owner", None, {row.id: row for row in rows}
    )


def test_report_catalogue_gives_each_present_actor_a_turn_before_adding_second_sources():
    minds, _, _ = chain()
    turn = SimpleNamespace(minds=minds, decisions={actor: object() for actor in minds})
    assert {origin.actor_id for origin in reports.catalogue(turn).values()} == set(minds)


def test_report_origins_reuse_old_retrieved_sources_before_unrelated_recent_speech():
    minds, _, _ = chain()
    original = next(iter(minds["CARDINAL"].sources))
    changed = minds["CARDINAL"]
    for index in range(3):
        changed = record(
            changed,
            Source(
                message_id=f"recent-{index}",
                content_hash="a" * 64,
                role="assistant",
                speaker_id="CARDINAL",
                kind="speech",
                text=f"Unrelated remark {index}.",
            ),
            minute=index + 2,
        )
    turn = SimpleNamespace(
        minds={"CARDINAL": changed},
        decisions={"CARDINAL": object()},
        semantic_hits={"CARDINAL": [SimpleNamespace(record_id=original)]},
    )
    selected = list(reports.catalogue(turn).values())
    assert len(selected) == 2 and selected[0].record_id == original


async def test_a_source_edited_after_model_review_is_rechecked_before_commit():
    from backend.models.chat import ChatMessage
    from tests.conftest import TestSessionLocal
    from tests.test_vn_turn_integration import seed_vn

    _, rows, turn = chain()
    async with TestSessionLocal() as db:
        _, _, state, _ = await seed_vn(db)
        saved = [
            ChatMessage(
                id=row.id,
                session_id=state.session_id,
                role=row.role,
                revision_id=row.revision_id,
                content=row.content,
                scene_id=row.scene_id,
            )
            for row in rows
        ]
        db.add_all(saved)
        await db.commit()
        # ChatMessage assigns a new revision at insert; bind fixtures to those canonical rows.
        for row, stored in zip(rows, saved, strict=True):
            stored.revision_id = row.revision_id
        await db.commit()
        manager = SimpleNamespace(db=db, game_id=state.session_id)
        await reports.validate_commit(manager, turn)
        saved[0].content = "Changed while narration was being reviewed."
        await db.flush()
        with pytest.raises(ValueError, match="provenance changed"):
            await reports.validate_commit(manager, turn)
