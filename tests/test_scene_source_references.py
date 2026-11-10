"""Scene evidence selects a source occurrence, not a matching phrase in later prose."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.narrated_items.runtime import reconcile_items
from backend.engine.scene_continuity import runtime
from backend.engine.scene_continuity.ledger import read
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldScene
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn

NARRATION = 'The kettle starts heating. Mira recalls: "The kettle starts heating."'
ROOM = "Cobalt walls and brass lamps surround a wooden bench."


@pytest.mark.parametrize("staging", [False, True])
async def test_scene_fact_source_is_bound_by_reference_not_model_label(monkeypatch, staging):
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        room = await db.scalar(select(WorldScene).where(WorldScene.id == "START"))
        room.description = ROOM
        write_settings(state, VnSettings(scene_staging=staging))
        await db.commit()
        calls = []

        async def extract(_system, payload, schema, *_args, **kwargs):
            body = json.loads(payload)
            calls.append((body, kwargs))
            reference = next(iter(body["completed_narration"]))
            return schema.model_validate(
                {
                    "scene_updates": [
                        {
                            "operation": "record",
                            "key": "kettle_heating",
                            "kind": "process",
                            "subject_id": "START",
                            "detail": "The kettle is heating.",
                            "source": "scene_description",
                            "evidence": reference,
                        }
                    ]
                }
            )

        monkeypatch.setattr(
            "backend.engine.narrated_items.runtime.GameMasterLLM.for_role",
            lambda *_: SimpleNamespace(model="local", aexecute_complex_task=extract),
        )
        manager = SimpleNamespace(
            db=db,
            user=user,
            avatar=avatar,
            state=state,
            game_id=state.session_id,
            _vn_player_message_id="input-1",
        )
        await reconcile_items(manager, NARRATION, completed=True, resolution="")
        reply = ChatMessage(
            session_id=state.session_id, role="assistant", content=NARRATION, scene_id="START"
        )
        db.add(reply)
        await db.flush()
        assert runtime.finish(manager, reply) == []
        await db.commit()
        await db.refresh(state)
        records = read(state.entity_states).records
        assert len(records) == 1
        fact = next(iter(records.values()))
        assert fact.origin.kind == "narration"
        assert fact.origin.source_id == reply.id
        assert fact.origin.revision_id == reply.revision_id
        assert fact.origin.quote == "The kettle starts heating."
        assert fact.origin.evidence_span.start == 0
        assert fact.origin.evidence_span.end == len(fact.origin.quote)
        assert len(calls) == 1
        assert "response_schema" in calls[0][1]


def test_repeated_phrase_has_distinct_spans_and_request_scoped_references():
    from backend.engine.narrated_items import evidence

    text = "The kettle starts heating. The kettle starts heating."
    first = evidence.Catalog(text, ROOM, scope="session:turn-1:START")
    second = evidence.Catalog(text, ROOM, scope="session:turn-2:START")
    refs = first.narration_passages
    assert len(refs) == 2 and len(set(refs.values())) == 1
    assert set(refs).isdisjoint(second.narration_passages)
    a, b = [first.resolve(key, allow_room=False) for key in refs]
    assert a.span.start == 0 and b.span.start > a.span.end
    assert a.quote == b.quote
    with pytest.raises(ValueError):
        second.resolve(next(iter(refs)), allow_room=False)


def test_room_source_cannot_authorize_a_current_pose_or_process():
    from backend.engine.narrated_items import evidence

    catalog = evidence.Catalog(NARRATION, ROOM, scope="test")
    reference = next(iter(catalog.room_passages))
    with pytest.raises(ValueError):
        catalog.resolve(reference, allow_room=False)


def test_same_words_in_room_and_narration_keep_different_source_identities():
    from backend.engine.narrated_items import evidence

    catalog = evidence.Catalog("The lamp is bright.", "The lamp is bright.", scope="test")
    n = catalog.resolve(next(iter(catalog.narration_passages)), allow_room=True)
    r = catalog.resolve(next(iter(catalog.room_passages)), allow_room=True)
    assert n.kind == "narration" and r.kind == "scene_description"
    assert n.quote == r.quote and n.reference != r.reference


def proposal(reference, **changes):
    return {
        "operation": "record",
        "key": "heating",
        "kind": "process",
        "subject_id": "START",
        "detail": "The kettle is heating.",
        "evidence": reference,
        **changes,
    }


def apply_bound(states, updates, catalog, message_id):
    from backend.engine.narrated_items.evidence import bind
    from backend.engine.narrated_items.schema import SharedItemExtraction
    from backend.engine.scene_continuity.ledger import apply

    bound = bind(SharedItemExtraction(scene_updates=updates), catalog.narration, catalog=catalog)
    return apply(
        states,
        bound.scene_updates,
        [],
        message=SimpleNamespace(
            id=message_id, revision_id="r-" + message_id, content=catalog.narration
        ),
        scene_id="START",
        scene_description=catalog.room,
        session_id="session",
        minute=10,
        targets={"START", "LINA"},
    )


def test_recollection_repetitions_cannot_retarget_the_original_fact():
    from backend.engine.narrated_items.evidence import Catalog

    original = Catalog("The kettle starts heating.", ROOM, scope="turn-1")
    reference = next(iter(original.narration_passages))
    states, errors = apply_bound({}, [proposal(reference)], original, "m1")
    assert not errors
    fact = next(iter(read(states).records.values()))
    proof = fact.origin.model_dump()
    for number in range(2, 6):
        recalled = Catalog(
            'Mira remembers: "The kettle starts heating."', ROOM, scope=f"turn-{number}"
        )
        states, errors = apply_bound(
            states,
            [proposal(reference, operation="change", record_id=fact.id, key="", subject_id="")],
            recalled,
            f"m{number}",
        )
        assert errors
        saved = read(states).records[fact.id]
        assert saved.origin.model_dump() == proof
        assert saved.latest == saved.origin
        assert saved.status == "active"


def test_room_reference_keeps_environment_rule_and_cannot_supply_a_process():
    from backend.engine.narrated_items.evidence import Catalog

    catalog = Catalog(NARRATION, ROOM, scope="test")
    reference = next(iter(catalog.room_passages))
    states, errors = apply_bound({}, [proposal(reference)], catalog, "m1")
    assert errors and not read(states).records
    states, errors = apply_bound(
        {}, [proposal(reference, kind="environment", detail="Cobalt walls.")], catalog, "m2"
    )
    assert not errors
    assert next(iter(read(states).records.values())).origin.kind == "scene_description"


def test_unknown_reference_cannot_become_valid_by_appearing_inside_the_story():
    from backend.engine.narrated_items.evidence import Catalog

    fake = "narration:0000000000000000:p0"
    catalog = Catalog("Mira quotes the identifier " + fake + ".", ROOM, scope="real-turn")
    states, errors = apply_bound({}, [proposal(fake)], catalog, "m1")
    assert errors and not read(states).records


def test_copy_and_retraction_preserve_occurrence_instead_of_searching_again():
    from backend.engine.narrated_items.evidence import Catalog
    from backend.engine.scene_continuity.lifecycle import remap, retract

    catalog = Catalog("The kettle starts heating.", ROOM, scope="turn-1")
    states, errors = apply_bound(
        {}, [proposal(next(iter(catalog.narration_passages)))], catalog, "original"
    )
    assert not errors
    copied = remap(states, {"original": "copy"})
    fact = next(iter(read(copied).records.values()))
    assert fact.origin.source_id == "copy"
    assert (
        fact.origin.evidence_span == next(iter(read(states).records.values())).origin.evidence_span
    )
    holder = SimpleNamespace(entity_states=copied)
    retract(holder, "copy")
    withdrawn = next(iter(read(holder.entity_states).records.values()))
    assert withdrawn.status == "unconfirmed"
    assert withdrawn.origin.evidence_span == fact.origin.evidence_span


def test_host_offsets_override_untrusted_model_offsets_and_legacy_shape_is_stable():
    from backend.engine.narrated_items.evidence import Catalog, bind
    from backend.engine.narrated_items.schema import SharedItemExtraction
    from backend.engine.scene_continuity.schema import Evidence

    text = "The kettle starts heating. The kettle starts heating."
    catalog = Catalog(text, ROOM, scope="test")
    reference = list(catalog.narration_passages)[1]
    body = proposal(reference, evidence_span={"start": 0, "end": 2})
    bound = bind(SharedItemExtraction(scene_updates=[body]), text, catalog=catalog)
    selected = bound.scene_updates[0]["evidence_span"]
    assert (
        selected["start"] > 0
        and text[selected["start"] : selected["end"]] == "The kettle starts heating."
    )
    legacy = {
        "kind": "narration",
        "source_id": "m",
        "revision_id": None,
        "content_hash": "a" * 64,
        "quote": "The kettle starts heating.",
    }
    assert Evidence.model_validate(legacy).model_dump() == legacy


def test_unicode_occurrence_offsets_are_character_positions_not_bytes():
    from backend.engine.narrated_items.evidence import Catalog

    text = "💡 Свет погас. 💡 Свет погас."
    catalog = Catalog(text, scope="unicode")
    for reference, quote in catalog.narration_passages.items():
        chosen = catalog.resolve(reference, allow_room=False)
        assert text[chosen.span.start : chosen.span.end] == quote


async def test_shared_sources_persist_for_room_pose_condition_prop_and_item(monkeypatch):
    from backend.engine.narrated_items.runtime import KEY
    from backend.engine.physical_conditions import runtime as physical
    from backend.engine.physical_conditions.ledger import read as physical_read
    from backend.engine.scene_staging import shared
    from backend.engine.visual_novel.runtime import capture_completed_moment
    from backend.models.world_entity import WorldEntity

    text = "Lina sits on the bench. Lina has a small cut on her left hand. Lina places her blue scarf on the table."
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        room = await db.scalar(select(WorldScene).where(WorldScene.id == "START"))
        room.description = ROOM
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        npc.inventory = [
            {"id": "SCARF", "name": "Blue scarf", "description": "A blue cotton scarf."}
        ]
        write_settings(state, VnSettings(scene_staging=True))
        await db.commit()
        calls = []

        async def extract(_instructions, payload, schema, *_args, **_kwargs):
            body = json.loads(payload)
            calls.append(body)
            n = list(body["completed_narration"])
            r = next(iter(body["scene_continuity"]["scene_description"]))
            return schema.model_validate(
                {
                    "actions": [
                        {
                            "item_id": "SCARF",
                            "source_owner": "LINA",
                            "destination_owner": "LINA",
                            "disposition": "carried",
                            "basis": "completed",
                            "evidence": n[2],
                        }
                    ],
                    "condition_updates": [
                        {
                            "operation": "record",
                            "target_id": "LINA",
                            "kind": "injury",
                            "part": "left hand",
                            "detail": "A small cut.",
                            "evidence": n[1],
                        }
                    ],
                    "scene_updates": [
                        proposal(
                            r,
                            kind="environment",
                            key="interior",
                            detail="Cobalt walls and brass lamps.",
                        )
                    ],
                    "staging": {
                        "changes": [{"entity_id": "LINA", "posture": "sitting", "evidence": n[0]}],
                        "props": [
                            {
                                "item_id": "SCARF",
                                "owner_id": "LINA",
                                "status": "confirmed",
                                "spatial_position": "on the table",
                                "evidence": n[2],
                            }
                        ],
                    },
                }
            )

        monkeypatch.setattr(
            "backend.engine.narrated_items.runtime.GameMasterLLM.for_role",
            lambda *_: SimpleNamespace(model="local", aexecute_complex_task=extract),
        )
        manager = SimpleNamespace(
            db=db,
            user=user,
            avatar=avatar,
            state=state,
            game_id=state.session_id,
            _vn_player_message_id="input",
        )
        assert await reconcile_items(manager, text, completed=True, resolution="")
        message = ChatMessage(
            session_id=state.session_id, role="assistant", content=text, scene_id="START"
        )
        db.add(message)
        await db.flush()
        assert physical.finish(manager, message) == []
        assert runtime.finish(manager, message) == []
        assert shared.consume(manager, text, completed=True)
        await capture_completed_moment(manager, message)
        await db.commit()
        await db.refresh(state)
        fact = next(iter(read(state.entity_states).records.values()))
        assert fact.origin.kind == "scene_description" and fact.origin.source_id == "START"
        assert fact.origin.evidence_span.matches(ROOM, fact.origin.quote)
        condition = next(iter(physical_read(state.entity_states).conditions.values()))
        assert condition.origin.message_id == message.id
        assert condition.origin.evidence_span.matches(text, condition.origin.quote)
        pose = state.entity_states["__scene_staging__"]["actors"]["LINA"]["posture"]
        assert pose["source_message_id"] == message.id and pose["evidence_span"]["start"] == 0
        prop = state.entity_states["__scene_props__"]["items"][0]
        assert (
            prop["source_message_id"] == message.id
            and prop["evidence_span"]["start"] > pose["evidence_span"]["end"]
        )
        item = state.entity_states[KEY]
        assert item["narration_source"]["message_id"] == message.id
        assert item["narration_source"]["revision_id"] == message.revision_id
        assert item["accepted"][0]["evidence_span"] == prop["evidence_span"]
        assert len(calls) == 1
