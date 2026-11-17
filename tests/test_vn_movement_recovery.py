"""Progression cannot replace source-qualified movement with unsupported history repair."""

import pytest
from sqlalchemy import select

from backend.core.text_evidence import EvidenceSpan
from backend.engine.chpm import identity_adapter, inference, rendering
from backend.engine.chpm.core.contracts import Genesis, Scope
from backend.engine.chpm.core.reducer import initial
from backend.engine.chpm.host_state import Mind, Source, record
from backend.engine.chpm.kernel import digest
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY, load
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.runtime import KEY as ITEMS
from backend.engine.narrated_movement.outcomes import MovementOutcome
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import final_payload, install_roles, seed_vn

DEPARTURE = "Lina walks through the door into the annex."


class RecoveringRoles(ChpmRoles):
    def __init__(self, *, proof=None, presence="audible", mutate=None):
        super().__init__()
        self.proof = proof
        self.presence = presence
        self.mutate = mutate

    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        schema = kwargs.get("response_model") or args[2]
        if not schema.__name__.startswith("VNProgressionIntent"):
            return result
        if self.mutate:
            await self.mutate()
        proof = {"movement_source": self.proof} if self.proof is not None else {}
        return schema.model_validate(
            {
                "moved_entities": [{"entity_id": "LINA", "to_scene_id": "ANNEX", **proof}],
                "updated_entities": [
                    {
                        "entity_id": "LINA",
                        "presence": self.presence,
                        "notes": "Now on the annex.",
                        **proof,
                    },
                    {"entity_id": "ABSENT", "notes": "Retain this independent note."},
                ],
            }
        )


async def recovery_state(db, *, mode, locked=False, status="unconfirmed", reviewed=True):
    user, avatar, state, previous_id = await seed_vn(db)
    actor = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
    actor.moveable = True
    previous = await db.get(ChatMessage, previous_id)
    previous.content = DEPARTURE
    span = EvidenceSpan(start=0, end=len(DEPARTURE))
    genesis = Genesis(
        scope=Scope(world_id=state.session_id, branch_id="session-main-v1", observer_id=actor.id),
        identity=identity_adapter.from_actor(actor),
    )
    source = Source(
        message_id=previous.id,
        revision_id=previous.revision_id,
        content_hash=digest(DEPARTURE),
        role="assistant",
        speaker_id=actor.id,
        kind="narration",
        text=DEPARTURE,
        action_span=span,
        movement_outcomes=(
            MovementOutcome(
                actor_id=actor.id, status=status, evidence=DEPARTURE, evidence_span=span
            ),
        ),
    )
    mind = record(Mind(genesis=genesis, snapshot=initial(genesis)), source, minute=0)
    state.entity_states = {
        **state.entity_states,
        KEY: KernelState(
            settings=Settings(mode=mode, actor_ids=[actor.id], failure_policy="strict"),
            minds={actor.id: mind} if reviewed else {},
        ).model_dump(mode="json"),
        ITEMS: {
            "movement_check": {
                "message_id": previous.id,
                "revision_id": previous.revision_id,
                "content_hash": digest(DEPARTURE),
                "outcomes": [entry.model_dump(mode="json") for entry in source.movement_outcomes],
            }
        },
    }
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
                exit_type="bidirectional",
                is_locked=locked,
            ),
        ]
    )
    await db.commit()
    return user, avatar, state


def install(monkeypatch, roles):
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)


def proof(kind="previous_narration", *, basis="completed", passage="history:p0"):
    return {"kind": kind, "basis": basis, "passage_id": passage}


@pytest.mark.parametrize("mode", ["off", "live"])
@pytest.mark.parametrize("locked", [False, True])
async def test_unproven_prior_departure_cannot_bypass_owner_or_skip_personality(
    monkeypatch, mode, locked
):
    roles = RecoveringRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state = await recovery_state(db, mode=mode, locked=locked)
        before_inventory = list(avatar.inventory)
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "I sit quietly and study the map."
            )
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        current = state.entity_states.get("LINA", {})
        assert current.get("current_scene_id", "START") == "START"
        assert current.get("presence", "present") == "present"
        assert "notes" not in current
        assert state.entity_states["ABSENT"]["notes"] == "Retain this independent note."
        assert state.current_scene_id == "START" and avatar.inventory == before_inventory
        assert roles.chpm_calls == (
            ["perception", "proposal", "validation"] if mode == "live" else []
        )
        assert load(state).settings.mode == mode


@pytest.mark.parametrize("mode", ["off", "live"])
async def test_valid_later_owner_revalidation_resolves_unconfirmed_departure(monkeypatch, mode):
    roles = RecoveringRoles(proof=proof(), presence="present")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode=mode)
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "I study the map."
            )
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        assert state.entity_states["LINA"]["current_scene_id"] == "ANNEX"
        assert state.entity_states["LINA"]["presence"] == "present"
        assert roles.chpm_calls == []
        assert not any("Some proposed movements need review" in event for event in events)


@pytest.mark.parametrize("mode", ["off", "live"])
@pytest.mark.parametrize(
    "gate", ["locked", "nonadjacent", "previously_blocked", "unowned", "conflicting_presence"]
)
async def test_source_proof_does_not_bypass_route_outcome_or_controller(monkeypatch, mode, gate):
    roles = RecoveringRoles(
        proof=proof(), presence="audible" if gate == "conflicting_presence" else "present"
    )
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(
            db,
            mode=mode,
            locked=gate == "locked",
            status="blocked" if gate == "previously_blocked" else "unconfirmed",
            reviewed=gate != "unowned",
        )
        if gate == "nonadjacent":
            edge = await db.scalar(
                select(WorldExit).where(WorldExit.session_id == state.session_id)
            )
            edge.from_scene_id = "FOREST"
            await db.commit()
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "I study the map."
            )
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        expected = "ANNEX" if gate == "unowned" and mode == "off" else "START"
        assert state.entity_states.get("LINA", {}).get("current_scene_id", "START") == expected
        assert state.entity_states["ABSENT"]["notes"] == "Retain this independent note."
        assert roles.chpm_calls == (
            ["perception", "proposal", "validation"] if mode == "live" else []
        )


@pytest.mark.parametrize("mode", ["off", "live"])
@pytest.mark.parametrize("basis", ["resolved_external_effect", "intention", "attempt", "completed"])
async def test_current_player_effect_has_its_own_namespace_and_resolution(monkeypatch, mode, basis):
    roles = RecoveringRoles(
        proof=proof("current_player_action", basis=basis, passage="player:p0"), presence="present"
    )
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode=mode, status="blocked")
        action = (
            "I push Lina through the door into the annex."
            if basis == "resolved_external_effect"
            else "I ask Lina to go to the annex."
        )
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(action)
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        expected = "ANNEX" if basis == "resolved_external_effect" else "START"
        assert state.entity_states.get("LINA", {}).get("current_scene_id", "START") == expected
        assert state.current_scene_id == "START"


@pytest.mark.parametrize("change", ["content", "revision", "namespace", "input", "malformed"])
async def test_stale_or_invalid_source_retains_npc_without_losing_independent_updates(
    monkeypatch, change
):
    async with TestSessionLocal() as db:
        user, _, state = await recovery_state(db, mode="off")
        previous = await db.scalar(select(ChatMessage).where(ChatMessage.role == "assistant"))

        async def mutate():
            if change == "content":
                previous.content += " Changed."
            if change == "revision":
                previous.revision_id = "new-revision"
            if change == "input":
                # Keep the active attempt current while invalidating the movement snapshot.
                manager._vn_movement_input = "different-input"
            await db.flush()

        supplied = proof(passage="player:p0" if change == "namespace" else "history:p0")
        if change == "malformed":
            supplied["start"] = 0
        roles = RecoveringRoles(proof=supplied, presence="present", mutate=mutate)
        install(monkeypatch, roles)
        manager = GameTurnManager(db, state.session_id, user)
        events = [event async for event in manager.process_turn("I study the map.")]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        assert state.entity_states.get("LINA", {}).get("current_scene_id", "START") == "START"
        assert state.entity_states["ABSENT"]["notes"] == "Retain this independent note."


async def test_changed_active_input_rejects_whole_progression_before_applying_updates(monkeypatch):
    async with TestSessionLocal() as db:
        user, avatar, state = await recovery_state(db, mode="off")

        async def change_input():
            manager._vn_player_message_id = "different-input"

        roles = RecoveringRoles(proof=proof(), presence="present", mutate=change_input)
        install(monkeypatch, roles)
        manager = GameTurnManager(db, state.session_id, user)
        inventory = list(avatar.inventory)

        events = [event async for event in manager.process_turn("I study the map.")]

        assert any(event.startswith("event: error") for event in events), "".join(events)
        assert not any(event.startswith("event: final") for event in events)
        assert roles.prompts == [] and roles.chpm_calls == []
        await db.refresh(state)
        await db.refresh(avatar)
        assert state.entity_states.get("LINA", {}).get("current_scene_id", "START") == "START"
        assert "notes" not in state.entity_states.get("ABSENT", {})
        assert state.current_scene_id == "START" and avatar.inventory == inventory
