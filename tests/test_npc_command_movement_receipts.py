"""Command-excluded movement retains its owner result across source reuse."""

import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.engine import turn_controls
from backend.engine.chpm import movement_feedback
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.state import KEY, load
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.visuals import session_objects
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.runtime import KEY as ITEMS
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.narrated_movement import runtime as movement
from backend.engine.narrated_movement.schema import MAX_MOVEMENTS
from backend.engine.npc_actions import reconciliation
from backend.engine.npc_actions.source_control import read as source_control
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.npc_control_support import bind_turn
from tests.state_response_fixture import extraction
from tests.test_chpm_host_turn import run
from tests.test_chpm_notebook_turn import ACTION, install
from tests.test_chpm_observable_turn import prepare
from tests.test_npc_action_empty_turn import EmptyPlanRoles
from tests.test_npc_action_lifecycle import controller_turn
from tests.test_npc_action_movement import movement_fixture
from tests.test_vn_turn_integration import NARRATION, final_payload

DEPARTURE = "Lina walks through the door into the annex."


def proposal(*, actor="LINA", text=DEPARTURE, start=0, **changes):
    return {
        "actor_id": actor,
        "destination_scene_id": "ANNEX",
        "basis": "completed",
        "evidence": text,
        "evidence_span": {"start": start, "end": start + len(text)},
        **changes,
    }


async def host(db, text=DEPARTURE, outcomes=None):
    manager, _, _, observed, draft = await movement_fixture(db)
    current = controller_turn(manager, observed, draft)
    current.action_outcomes = outcomes or {"LINA": []}
    manager._chpm_turn = bind_turn(manager, current)
    rows = await session_objects(db, manager.game_id)
    await movement.prepare(manager, rows, text)
    return manager, actor_records(manager, rows)


async def finish(manager, actors, proposals, *, text=DEPARTURE, confirmed=True, publish=True):
    original = ItemExtraction(movements=proposals)
    if publish:
        guarded, _, _, _, _ = reconciliation.unpack(manager, original, actors)
    else:
        guarded, _, _ = reconciliation.protect(manager, original)
    movement.complete(manager, guarded.movements, confirmed=confirmed)
    manager.state.entity_states = {**manager.state.entity_states, ITEMS: {}}
    reply = ChatMessage(
        session_id=manager.game_id, role="assistant", content=text, scene_id="START"
    )
    manager.db.add(reply)
    await manager.db.flush()
    await movement.finish(manager, reply)
    return reply, movement_feedback.read(manager.state, reply)


@pytest.mark.parametrize("confirmed", [True, False])
@pytest.mark.parametrize("occurrence", [0, 1])
async def test_excluded_completed_occurrence_survives_empty_or_unconfirmed_extraction(
    confirmed, occurrence
):
    text = DEPARTURE + "\n" + DEPARTURE
    start = occurrence * (len(DEPARTURE) + 1)
    async with TestSessionLocal() as db:
        manager, actors = await host(db, text)
        _, outcomes = await finish(
            manager, actors, [proposal(start=start)], text=text, confirmed=confirmed
        )
        assert len(outcomes) == 1
        assert outcomes[0].actor_id == "LINA" and outcomes[0].status == "blocked"
        assert outcomes[0].evidence_span.start == start and outcomes[0].evidence == DEPARTURE


@pytest.mark.parametrize(
    "effect,changes,blocked",
    [
        ({"destination_scene_id": "ANNEX"}, {}, False),
        ({"presence": "absent"}, {"destination_scene_id": None, "presence": "absent"}, False),
        ({"destination_scene_id": "ANNEX"}, {"destination_scene_id": None}, True),
        ({"item_id": "HIDDEN_RING"}, {"destination_scene_id": None, "presence": "absent"}, True),
        ({"posture": "sitting"}, {"destination_scene_id": None, "presence": "absent"}, True),
    ],
)
async def test_echoes_require_the_same_explicit_movement_fields(effect, changes, blocked):
    async with TestSessionLocal() as db:
        manager, actors = await host(
            db, outcomes={"LINA": [{"status": "applied", "effect": effect}]}
        )
        _, outcomes = await finish(manager, actors, [proposal(**changes)])
        assert bool(outcomes) is blocked
        assert all(row.status == "blocked" for row in outcomes)


@pytest.mark.parametrize(
    "change",
    ["narration", "scene", "attempt", "input", "saved_revision", "saved_contents", "saved_role"],
)
async def test_stale_sources_and_attempts_do_not_publish_a_command_denial(change):
    async with TestSessionLocal() as db:
        manager, actors = await host(db)
        original = ItemExtraction(movements=[proposal()])
        guarded, _, _, _, _ = reconciliation.unpack(manager, original, actors)
        movement.complete(manager, guarded.movements)
        if change == "scene":
            manager.state.current_scene_id = "ANNEX"
        if change == "attempt":
            turn_controls.begin(manager)
        if change == "input":
            manager._vn_player_message_id = "another-input"
        if change.startswith("saved_"):
            saved = await db.get(ChatMessage, manager._vn_player_message_id)
            if change == "saved_revision":
                saved.revision_id = "changed"
            elif change == "saved_contents":
                saved.content += " Changed."
            else:
                saved.role = "assistant"
            await db.flush()
        manager.state.entity_states = {**manager.state.entity_states, ITEMS: {}}
        reply = ChatMessage(
            session_id=manager.game_id,
            role="assistant",
            content=DEPARTURE + (" Changed." if change == "narration" else ""),
        )
        db.add(reply)
        await db.flush()
        await movement.finish(manager, reply)
        assert movement_feedback.read(manager.state, reply) == ()


@pytest.mark.parametrize("basis", ["attempt", "intention", "uncertain", "historical"])
async def test_unperformed_candidates_are_not_fabricated_as_blocked_attempts(basis):
    async with TestSessionLocal() as db:
        manager, actors = await host(db)
        _, outcomes = await finish(manager, actors, [proposal(basis=basis)])
        assert outcomes == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence": "An unavailable source quote."},
        {"evidence_span": {"start": 1, "end": 1 + len(DEPARTURE)}},
        {"evidence": None},
        {"actor_id": "UNKNOWN"},
    ],
)
async def test_invalid_sources_or_actor_identity_do_not_acquire_command_denials(changes):
    async with TestSessionLocal() as db:
        manager, actors = await host(db)
        _, outcomes = await finish(manager, actors, [proposal(**changes)])
        assert all(row.status != "blocked" for row in outcomes)


async def test_attempt_closed_during_owner_context_read_cannot_publish_denials(monkeypatch):
    async with TestSessionLocal() as db:
        manager, actors = await host(db)
        original_context = movement.context

        async def closed(*args, **kwargs):
            result = await original_context(*args, **kwargs)
            turn_controls.close(manager)
            return result

        monkeypatch.setattr(movement, "context", closed)
        rows = [proposal(), proposal(actor="ABSENT")]
        _, outcomes = await finish(manager, actors, rows)
        assert all(row.actor_id != "LINA" for row in outcomes)


async def test_a_correction_preview_cannot_stage_an_owner_denial():
    async with TestSessionLocal() as db:
        manager, actors = await host(db)
        _, outcomes = await finish(manager, actors, [proposal()], publish=False)
        assert outcomes == ()


@pytest.mark.parametrize("count", [MAX_MOVEMENTS, MAX_MOVEMENTS + 1])
async def test_original_batch_bound_keeps_independent_actors_and_receipts_within_the_same_limit(
    count,
):
    texts = [f"Lina leaves by route {index}." for index in range(count - 1)] + [
        "Mira leaves the room."
    ]
    text = "\n".join(texts)
    async with TestSessionLocal() as db:
        manager, _ = await host(db, text)
        other = await db.scalar(select(WorldEntity).where(WorldEntity.id == "ABSENT"))
        other.current_scene_id, other.moveable = "START", True
        await db.flush()
        rows = await session_objects(db, manager.game_id)
        actors = actor_records(manager, rows)
        await movement.prepare(manager, rows, text)
        starts = [sum(len(value) + 1 for value in texts[:index]) for index in range(count)]
        proposals = [
            proposal(
                actor="ABSENT" if index == count - 1 else "LINA", text=quote, start=starts[index]
            )
            for index, quote in enumerate(texts)
        ]
        _, outcomes = await finish(manager, actors, proposals, text=text)
        position = manager.state.entity_states.get("ABSENT", {}).get("current_scene_id", "START")
        assert position == ("ANNEX" if count == MAX_MOVEMENTS else "START")
        assert len(outcomes) == (MAX_MOVEMENTS if count == MAX_MOVEMENTS else 0)
        assert all(row.status == "blocked" for row in outcomes if row.actor_id == "LINA")


class RecoveryRoles(EmptyPlanRoles):
    def __init__(self, source_kind="exact"):
        super().__init__()
        self.recover = False
        self.source_kind = source_kind

    def first_text(self):
        return DEPARTURE + "\n" + DEPARTURE if self.source_kind == "ambiguous" else DEPARTURE

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if issubclass(schema, ItemExtraction):
            count = MAX_MOVEMENTS + 1 if self.source_kind == "oversized" else 1
            return extraction(schema, movements=[] if self.recover else [proposal()] * count)
        result = await super().structured(*args, **kwargs)
        if self.recover and schema.__name__.startswith("VNProgressionIntent"):
            changes = [
                {
                    "entity_id": "LINA",
                    "to_scene_id": "ANNEX",
                    "movement_source": {
                        "kind": "previous_narration",
                        "basis": "completed",
                        "passage_id": "history:p0",
                    },
                }
            ]
            return schema.model_validate({**result.model_dump(), "moved_entities": changes})
        return result

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") != "validation" or self.recover:
            return await super().simple(system, payload, model, **kwargs)
        supplied = json.loads(payload)
        self.chpm_calls.append("validation")
        return json.dumps(
            {
                "review_scope": supplied["review_scope"],
                "matches": True,
                "actions": [{"actor_id": "LINA", "passage_id": "p0"}],
            }
        )

    async def stream(self, *args, **kwargs):
        self.prompts.append((args, kwargs))
        text = NARRATION if self.recover else self.first_text()

        async def chunks():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=text))])

        return chunks()


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("source_kind", ["exact", "ambiguous", "oversized"])
@pytest.mark.parametrize("current_mode", ["live", "off"])
async def test_pipeline_generated_denial_survives_reload_and_prevents_next_turn_history_execution(
    monkeypatch, protocol, source_kind, current_mode
):
    roles = RecoveryRoles(source_kind)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", protocol, False)
        actor = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        actor.moveable = True
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        db.add_all(
            [
                WorldScene(
                    id="ANNEX", session_id=state.session_id, label="Annex", description="A room."
                ),
                WorldExit(
                    session_id=state.session_id,
                    from_scene_id="START",
                    to_scene_id="ANNEX",
                    label="Door",
                    is_locked=False,
                ),
            ]
        )
        await db.commit()
        manager, events = await run(db, user, ACTION)
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        decision = load(state).actors["LINA"]
        reply_id = decision.reply_id
        reply = await db.get(ChatMessage, reply_id)
        assert state.entity_states.get("LINA", {}).get("current_scene_id", "START") == "START"
        assert reply.content == roles.first_text() and decision.action_evidence == DEPARTURE
        assert source_control(reply).valid and source_control(reply).actor_ids == {"LINA"}
        if source_kind != "exact":
            assert movement_feedback.read(state, reply) == ()
        state_id, user_id = state.id, user.id
    roles.recover = True
    async with TestSessionLocal() as db:
        state = await db.get(SessionState, state_id)
        user = await db.get(User, user_id)
        if current_mode == "off":
            kernel = load(state)
            kernel.settings.mode = "off"
            state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
            await db.commit()
        manager = GameTurnManager(db, state.session_id, user)
        events = [event async for event in manager.process_turn("I study the map.")]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        assert state.entity_states.get("LINA", {}).get("current_scene_id", "START") == "START"
        source = next(
            entry
            for entry in load(state).minds["LINA"].sources.values()
            if entry.message_id == reply_id and entry.kind == "narration"
        )
        assert source.content_hash == digest(roles.first_text())
        if source_kind == "exact":
            assert source.movement_outcomes[0].status == "blocked"
        else:
            assert source.movement_outcomes == ()
