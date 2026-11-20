"""Recovery preserves source-time ownership, exact occurrences and existing turn effects."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.core.text_evidence import EvidenceSpan
from backend.engine.chpm.core.reducer import initial
from backend.engine.chpm.host_state import Mind, Source, record
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.recovery_contracts import RecoveryAudit, SimplifiedReply
from backend.engine.chpm.state import KEY, load
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.runtime import KEY as ITEMS
from backend.engine.narrated_movement.context import context
from backend.engine.narrated_movement.outcomes import MovementOutcome
from backend.engine.rule_engine import ExitUpdate
from backend.engine.visual_novel.intent import VNEntityUpdate
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldExit
from tests.conftest import TestSessionLocal
from tests.test_vn_movement_recovery import (
    DEPARTURE,
    RecoveringRoles,
    install,
    proof,
    recovery_state,
)
from tests.test_vn_turn_integration import final_payload


async def previous_reply(db):
    return await db.scalar(select(ChatMessage).where(ChatMessage.role == "assistant"))


async def turn(db, user, state, action="I study the map."):
    manager = GameTurnManager(db, state.session_id, user)
    events = [event async for event in manager.process_turn(action)]
    assert final_payload(events)["status"] == "success", "".join(events)
    await db.refresh(state)
    return events


@pytest.mark.parametrize(
    "kind", ["audit", "legacy", "consumed_audit", "stale_audit", "blocked_audit"]
)
async def test_valid_source_bound_fallback_can_recover_without_a_selected_decision(
    monkeypatch, kind
):
    roles = RecoveringRoles(proof=proof(), presence="present")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode="live", reviewed=False)
        reply = await previous_reply(db)
        kernel = load(state)
        kernel.recovery.recent = [
            SimplifiedReply(
                input_id="prior-input",
                reply_id=reply.id,
                reply_revision=reply.revision_id,
                reply_hash=digest(reply.content),
                reason="cooldown",
                actor_ids=["LINA"],
            )
        ]
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump(mode="json")}
        if kind != "legacy":
            outcomes = ()
            if kind == "blocked_audit":
                outcomes = (
                    MovementOutcome(
                        actor_id="LINA",
                        status="blocked",
                        evidence=DEPARTURE,
                        evidence_span=EvidenceSpan(start=0, end=len(DEPARTURE)),
                    ),
                )
            reply.npc_recovery = RecoveryAudit(
                content_hash=digest("changed" if kind == "stale_audit" else reply.content),
                revision_id=reply.revision_id,
                scene_id="START",
                actors={} if kind == "consumed_audit" else {"LINA": 0},
                movement_outcomes=outcomes,
            ).model_dump(mode="json")
        await db.commit()
        events = await turn(db, user, state)
        allowed = kind not in {"stale_audit", "blocked_audit"}
        assert state.entity_states.get("LINA", {}).get("current_scene_id", "START") == (
            "ANNEX" if allowed else "START"
        )
        assert (
            any("Some proposed movements need review" in event for event in events) is not allowed
        )


@pytest.mark.parametrize("mode", ["off", "live"])
@pytest.mark.parametrize("selected", [0, 1])
async def test_repeated_words_do_not_share_a_movement_receipt_or_action_occurrence(
    monkeypatch, mode, selected
):
    roles = RecoveringRoles(proof=proof(passage=f"history:p{selected}"), presence="present")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode=mode)
        reply = await previous_reply(db)
        reply.content = f"{DEPARTURE} {DEPARTURE}"
        first = MovementOutcome(
            actor_id="LINA",
            status="blocked",
            evidence=DEPARTURE,
            evidence_span=EvidenceSpan(start=0, end=len(DEPARTURE)),
        )
        second_span = EvidenceSpan(start=len(DEPARTURE) + 1, end=len(reply.content))
        second = MovementOutcome(
            actor_id="LINA", status="unconfirmed", evidence=DEPARTURE, evidence_span=second_span
        )
        kernel = load(state)
        genesis = kernel.minds["LINA"].genesis
        source = Source(
            message_id=reply.id,
            revision_id=reply.revision_id,
            content_hash=digest(reply.content),
            role="assistant",
            speaker_id="LINA",
            kind="narration",
            text=DEPARTURE,
            action_span=second_span,
            movement_outcomes=(second,),
        )
        kernel.minds["LINA"] = record(
            Mind(genesis=genesis, snapshot=initial(genesis)), source, minute=0
        )
        state.entity_states = {
            **state.entity_states,
            KEY: kernel.model_dump(mode="json"),
            ITEMS: {
                "movement_check": {
                    "message_id": reply.id,
                    "revision_id": reply.revision_id,
                    "content_hash": digest(reply.content),
                    "outcomes": [row.model_dump(mode="json") for row in (first, second)],
                }
            },
        }
        await db.commit()
        await turn(db, user, state)
        assert state.entity_states.get("LINA", {}).get("current_scene_id", "START") == (
            "ANNEX" if selected == 1 else "START"
        )


@pytest.mark.parametrize("override", [True, False])
async def test_effective_session_lock_controls_recovery(monkeypatch, override):
    roles = RecoveringRoles(proof=proof(), presence="present")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode="off", locked=not override)
        edge = await db.scalar(select(WorldExit).where(WorldExit.session_id == state.session_id))
        state.exit_states = {edge.id: {"is_locked": override}}
        await db.commit()
        await turn(db, user, state)
        assert state.entity_states.get("LINA", {}).get("current_scene_id", "START") == (
            "START" if override else "ANNEX"
        )


@pytest.mark.parametrize("mode", ["off", "live"])
@pytest.mark.parametrize("gate", ["stationary", "allowed_scenes", "locked"])
async def test_mobility_and_allowed_scenes_still_apply_to_current_forced_effects(
    monkeypatch, mode, gate
):
    roles = RecoveringRoles(
        proof=proof("current_player_action", basis="resolved_external_effect", passage="player:p0"),
        presence="present",
    )
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode=mode, locked=gate == "locked")
        state.entity_states = {
            **state.entity_states,
            "LINA": {
                "moveable": gate != "stationary",
                "allowed_scenes": ["START"] if gate == "allowed_scenes" else [],
            },
        }
        await db.commit()
        await turn(db, user, state, "I push Lina through the door into the annex.")
        assert state.entity_states["LINA"].get("current_scene_id", "START") == "START"


class UnlockRoles(RecoveringRoles):
    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        if type(result).__name__.startswith("VNProgressionIntent"):
            result.updated_exits = [
                ExitUpdate(from_scene_id="START", to_scene_id="ANNEX", is_locked=False)
            ]
        return result


@pytest.mark.parametrize("status", ["unconfirmed", "blocked"])
@pytest.mark.parametrize("code", ["1234", "9999"])
async def test_same_turn_unlock_is_validated_before_recovery_but_cannot_rewrite_blocked_history(
    monkeypatch, status, code
):
    roles = UnlockRoles(proof=proof(), presence="present")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode="off", status=status, locked=True)
        edge = await db.scalar(select(WorldExit).where(WorldExit.session_id == state.session_id))
        edge.code_to_unlock = "1234"
        await db.commit()
        await turn(db, user, state, f"I enter {code} on the door lock.")
        expected = "ANNEX" if code == "1234" and status == "unconfirmed" else "START"
        assert state.entity_states.get("LINA", {}).get("current_scene_id", "START") == expected
        await db.refresh(edge)
        assert edge.is_locked is (code != "1234")


class LocalRoles(RecoveringRoles):
    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        if type(result).__name__.startswith("VNProgressionIntent"):
            result.moved_entities = []
            result.updated_entities = [
                VNEntityUpdate(
                    entity_id="LINA",
                    spatial_position="Beside the map",
                    movement_source=self.proof,
                )
            ]
        return result


async def test_stationary_npc_local_pose_keeps_existing_mobility_semantics(monkeypatch):
    roles = LocalRoles(proof=proof())
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode="off")
        state.entity_states = {**state.entity_states, "LINA": {"moveable": False}}
        await db.commit()
        await turn(db, user, state)
        assert state.entity_states["LINA"]["spatial_position"] == "Beside the map"
        assert state.entity_states["LINA"].get("current_scene_id", "START") == "START"


@pytest.mark.parametrize("mode", ["off", "live"])
async def test_full_replay_rewinds_recovery_and_rebuilds_source_snapshot(monkeypatch, mode):
    roles = RecoveringRoles(proof=proof(), presence="present")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode=mode)
        manager = GameTurnManager(db, state.session_id, user)
        first = [event async for event in manager.process_turn("I study the map.")]
        assert final_payload(first)["status"] == "success", "".join(first)
        await db.refresh(state)
        assert state.entity_states["LINA"]["current_scene_id"] == "ANNEX"
        reply = await db.scalar(
            select(ChatMessage)
            .where(ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
        roles.proof = None
        roles.presence = "audible"
        retry = [
            event async for event in manager.process_turn("ignored", replay_message_id=reply.id)
        ]
        assert final_payload(retry)["status"] == "success", "".join(retry)
        await db.refresh(state)
        assert state.entity_states.get("LINA", {}).get("current_scene_id", "START") == "START"
        assert state.entity_states.get("LINA", {}).get("presence", "present") == "present"
        assert roles.chpm_calls == (
            ["perception", "proposal", "validation"] if mode == "live" else []
        )
        names = [row[0] for row in roles.calls]
        assert sum(name.startswith("VNProgressionIntent") for name in names) == 2


class ExitUpdateRoles(UnlockRoles):
    def __init__(self, *, locked, **kwargs):
        super().__init__(**kwargs)
        self.locked = locked

    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        if type(result).__name__.startswith("VNProgressionIntent"):
            result.updated_exits[0].is_locked = self.locked
        return result


@pytest.mark.parametrize(
    "override,updated", [(True, False), (False, True), (None, False), (None, True)]
)
async def test_accepted_exit_update_supersedes_old_override_and_survives_owner_reload(
    monkeypatch, override, updated
):
    roles = ExitUpdateRoles(locked=updated, proof=proof(), presence="present")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode="off", locked=not updated)
        edge = await db.scalar(select(WorldExit).where(WorldExit.session_id == state.session_id))
        lock = {"is_locked": override, "lock_description": "Preserve this."}
        keys = [edge.id, "START:ANNEX", "ANNEX:START"]
        state.exit_states = {**{key: dict(lock) for key in keys}, "unrelated": {"keep": True}}
        await db.commit()
        await turn(db, user, state, "I operate the door lock.")
        assert state.entity_states.get("LINA", {}).get("current_scene_id", "START") == (
            "START" if updated else "ANNEX"
        )
        await db.refresh(edge)
        assert edge.is_locked is updated
        assert all(state.exit_states[key] == {**lock, "is_locked": updated} for key in keys)
        assert state.exit_states["unrelated"] == {"keep": True}
        projection = await context(SimpleNamespace(db=db, state=state), [])
        assert projection["routes"][0]["locked"] is updated


async def test_off_mode_recovery_does_not_load_unused_invalid_psychology(monkeypatch):
    roles = RecoveringRoles(proof=proof(), presence="present")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode="off", reviewed=False)
        envelope = dict(state.entity_states[KEY])
        envelope["minds"] = {"LINA": {"invalid-unused-mind": True}}
        state.entity_states = {**state.entity_states, KEY: envelope}
        await db.commit()
        await turn(db, user, state)
        assert state.entity_states["LINA"]["current_scene_id"] == "ANNEX"
        assert state.entity_states[KEY]["minds"] == {"LINA": {"invalid-unused-mind": True}}
        assert roles.chpm_calls == []
