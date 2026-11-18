"""Unperformed wardrobe attempts remain proposals without aborting unrelated facts."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.engine.chpm.state import KEY, load
from backend.engine.clothing.actions import CLOTHING_PROMPT, ClothingEvidence, WardrobeAction
from backend.engine.clothing.debug_wardrobe import WardrobeAction as DebugWardrobeAction
from backend.engine.clothing.outcomes import outcome
from backend.engine.clothing.planning import validate_plan
from backend.engine.clothing.runtime import LEDGER_KEY, apply_wardrobe
from backend.engine.physical_conditions.ledger import read
from backend.engine.rule_engine import GameEvent
from backend.engine.visual_novel.continuity import PLAYER, possession_snapshot
from backend.engine.visual_novel.intent import VNProgressionIntent, progression_schema
from backend.models.avatar import Avatar
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_action_turn import STATE, ActionRoles
from tests.test_chpm_host_turn import run
from tests.test_chpm_notebook_turn import install
from tests.test_chpm_observable_turn import prepare
from tests.test_clothing_runtime import action, creation, item, profile, world
from tests.test_vn_turn_integration import TurnRoles, install_roles, seed_vn

ATTEMPT = "I try to adjust the blue coat."
INDEPENDENT = "I put on my blue coat."


def attempted(**changes):
    return (
        action().model_dump()
        | {
            "evidence": ATTEMPT,
            "basis": "attempt",
            "operation": "adjust",
            "uncovered_regions": ["arms"],
        }
        | changes
    )


@pytest.mark.parametrize("tools", [False, True])
def test_dynamic_progression_accepts_attempt_without_promoting_it(tools):
    state = SimpleNamespace(
        entity_states={
            KEY: {
                "settings": {
                    "mode": "live",
                    "workflow": "integrated",
                    "action_tools": tools,
                    "actor_ids": ["ANNA"],
                    "agent_steps": 2,
                }
            }
        }
    )
    schema = progression_schema(state)
    assert ("player_item_actions" in schema.model_fields) == tools
    raw = {"extra_time_minutes": 3, "wardrobe_actions": [attempted()]}
    if tools:
        raw["player_item_actions"] = []
    result = schema.model_validate(raw)
    assert result.wardrobe_actions[0].basis == "attempt"
    assert result.wardrobe_actions[0].npc_decision == "not_established"
    assert result.extra_time_minutes == 3
    contract = schema.model_json_schema()["$defs"]
    assert "attempt" in contract["WardrobeAction"]["properties"]["basis"]["enum"]
    assert "attempt" not in contract["GarmentCreation"]["properties"]["basis"]["enum"]
    assert "attempt" in CLOTHING_PROMPT


def test_attempt_does_not_expand_acquisition_evidence_or_debug_authority():
    with pytest.raises(ValidationError):
        creation(basis="attempt")
    evidence = action().model_dump(exclude={"item_id", "operation", "uncovered_regions"})
    with pytest.raises(ValidationError):
        ClothingEvidence.model_validate(evidence | {"basis": "attempt"})
    with pytest.raises(ValidationError):
        DebugWardrobeAction.model_validate(
            {"npc_id": "ANNA", "item_id": "hat", "operation": "wear", "basis": "attempt"}
        )
    with pytest.raises(ValidationError):
        WardrobeAction.model_validate(attempted(basis="intention"))


@pytest.mark.parametrize(
    "basis", ["performed", "claim", "past", "future", "hypothetical", "negated", "uncertain"]
)
def test_existing_wardrobe_evidence_values_still_load(basis):
    assert WardrobeAction.model_validate(attempted(basis=basis)).basis == basis


@pytest.mark.parametrize("operation", ["wear", "remove", "adjust"])
@pytest.mark.parametrize("source", ["player_action", "completed_narration"])
@pytest.mark.parametrize("actor_id", [PLAYER, "ANNA"])
async def test_attempt_never_changes_wear_custody_or_consent(operation, source, actor_id):
    manager, npc, scenes = world()
    owner = manager.avatar if actor_id == PLAYER else npc
    identifier = "coat" if actor_id == PLAYER else "hat"
    owner.visual_profile = profile() if operation == "wear" else profile(identifier)
    await apply_wardrobe(manager, GameEvent(), manager.state.entity_states)
    possessions = deepcopy(possession_snapshot(manager, [npc]))
    before = deepcopy(
        (manager.avatar.visual_profile, npc.visual_profile, manager.state.entity_states)
    )
    change = attempted(
        actor_id=actor_id,
        item_id=identifier,
        source=source,
        operation=operation,
        agency="consented_assistance",
        npc_decision="approved",
        uncovered_regions=["arms"] if operation == "adjust" else [],
    )
    proposal = VNProgressionIntent.model_validate({"wardrobe_actions": [change]})
    event = GameEvent()
    event._vn_clothing_plan = validate_plan(manager, proposal, ATTEMPT, ATTEMPT, [npc], scenes)
    assert not event._vn_clothing_plan.actions
    assert event._vn_clothing_plan.rejected == proposal.wardrobe_actions
    await apply_wardrobe(manager, event, manager.state.entity_states)
    assert possession_snapshot(manager, [npc]) == possessions
    assert (manager.avatar.visual_profile, npc.visual_profile) == before[:2]
    assert {
        key: value for key, value in manager.state.entity_states.items() if key != LEDGER_KEY
    } == before[2]
    receipts = outcome(event)
    assert len(receipts) == 1
    assert receipts[0]["status"] == "blocked"
    assert receipts[0]["reason_code"] == "proposal_ungrounded"
    assert receipts[0]["actor_id"] == actor_id and receipts[0]["item_id"] == identifier
    assert "worn" not in receipts[0] and "uncovered_regions" not in receipts[0]


class AttemptRoles(TurnRoles):
    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        result = await super().structured(*args, **kwargs)
        if not schema.__name__.startswith("VNProgressionIntent"):
            return result
        return schema.model_validate(
            result.model_dump()
            | {
                "extra_time_minutes": 3,
                "updated_entities": [{"entity_id": "LINA", "notes": "The clock is repaired."}],
                "wardrobe_actions": [
                    attempted(
                        actor_id="LINA",
                        item_id="NPC_COAT",
                        npc_decision="approved",
                        agency="npc_choice",
                    ),
                    action().model_dump(),
                ],
            }
        )


async def test_real_turn_retains_valid_clothing_time_scene_and_social_facts(monkeypatch):
    roles = AttemptRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        avatar.inventory, avatar.visual_profile = [item()], profile()
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        npc.inventory, npc.visual_profile = [item("NPC_COAT")], profile("NPC_COAT")
        before_time = state.in_game_time
        await db.commit()
        manager, chunks = await run(db, user, f"{ATTEMPT} {INDEPENDENT}")
        assert any(row.startswith("event: final") for row in chunks), "".join(chunks)
        assert not any(row.startswith("event: error") for row in chunks), "".join(chunks)
        assert state.in_game_time - before_time == 3
        assert state.current_scene_id == "START"
        assert state.entity_states["LINA"]["notes"] == "The clock is repaired."
        assert avatar.visual_profile["worn"][0]["item_id"] == "coat"
        assert not state.entity_states.get("LINA", {}).get("visual_profile", npc.visual_profile)[
            "worn"
        ][0]["uncovered_regions"]
        assert [row["id"] for row in avatar.inventory] == ["coat"]
        assert [row["id"] for row in npc.inventory] == ["NPC_COAT"]
        assert "InteractionPlan" in {name for name, *_ in roles.calls}
        assert "not_completed" in str(roles.prompts[-1])
        await db.commit()
        await db.refresh(avatar)
        await db.refresh(state)
        assert avatar.visual_profile["worn"][0]["item_id"] == "coat"
        assert state.entity_states["LINA"]["notes"] == "The clock is repaired."
        assert manager.state.current_scene_id == "START"


class LiveAttemptRoles(ActionRoles):
    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        result = await super().structured(*args, **kwargs)
        if not schema.__name__.startswith("VNProgressionIntent"):
            return result
        return schema.model_validate(
            result.model_dump() | {"wardrobe_actions": [attempted()], "extra_time_minutes": 2}
        )


async def test_real_attempt_leaves_independent_live_npc_decision_and_commands_enabled(monkeypatch):
    roles = LiveAttemptRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await prepare(db, "integrated", "json", False)
        avatar = await db.get(Avatar, state.avatar_id)
        avatar.inventory, avatar.visual_profile = [item()], profile("coat")
        before_inventory = deepcopy(avatar.inventory)
        kernel = load(state)
        kernel.settings.action_tools = True
        state.entity_states = {**state.entity_states, KEY: kernel.model_dump()}
        await db.commit()
        manager, chunks = await run(db, user, ATTEMPT)
        assert any(row.startswith("event: final") for row in chunks), "".join(chunks)
        assert not any(row.startswith("event: error") for row in chunks), "".join(chunks)
        assert "integrated_decision" in roles.chpm_calls
        assert "validation" in roles.chpm_calls
        assert roles.reconciliations[-1]["owners"]["HIDDEN_RING"] == "__scene__"
        assert any(
            row.part == "surface" and row.detail == STATE and row.latest.kind == "command"
            for row in read(state.entity_states).conditions.values()
        )
        assert load(state).actors["LINA"].reply_id
        assert manager.avatar.inventory == before_inventory
        assert manager.avatar.visual_profile["worn"][0]["item_id"] == "coat"
        assert manager.avatar.visual_profile["worn"][0]["uncovered_regions"] == []
