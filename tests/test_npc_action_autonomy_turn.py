"""Self-directed NPC actions use the same canonical pipeline in all personality modes."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.chpm import inference, rendering
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.semantic_choice import previous_context
from backend.engine.chpm.state import KEY, load
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.runtime import KEY as ITEMS_KEY
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.scene_staging import props
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from tests.chpm_projection_fixture import public_projection
from tests.chpm_reference_fixture import response as reference_response
from tests.conftest import TestSessionLocal
from tests.test_chpm_kernel import motivated_candidates, preferred_choice
from tests.test_shared_scene_staging import ACTION, TEXT, SharedRoles, seed
from tests.test_vn_turn_integration import final_payload


class AutonomousRoles(SharedRoles):
    def __init__(self):
        super().__init__()
        self.phases = []
        self.intention = "Take off my coat, put it on the bench and sit beside the visitor."
        self.movements = []

    def for_role(self, user, role, **kwargs):
        model = super().for_role(user, role, **kwargs)
        model.max_tokens = 4096
        model.request_timeout = 10
        model.aexecute_simple_task = self.reference_simple
        return model

    async def reference_simple(self, system, payload, model, **kwargs):
        return reference_response(
            await self.simple(system, payload, model, **kwargs), json.loads(payload)
        )

    async def structured(self, *args, **kwargs):
        result = await super().structured(*args, **kwargs)
        schema = kwargs.get("response_model") or args[2]
        if self.movements and issubclass(schema, ItemExtraction):
            return schema.model_validate({**result.model_dump(), "movements": self.movements})
        return result

    async def simple(self, _system, payload, _model, **kwargs):
        phase = kwargs.get("phase")
        self.phases.append(phase)
        supplied = json.loads(payload)
        if phase == "perception":
            return json.dumps(public_projection(supplied))
        if phase == "validation":
            passage = next(iter(supplied["passages"]))
            return json.dumps(
                {
                    "matches": True,
                    "evidence": [],
                    "actions": [{"actor_id": "LINA", "passage_id": passage}],
                }
            )
        assert phase == "proposal"
        return json.dumps(
            {
                **(
                    {
                        "new_beliefs": [],
                        "belief_revisions": [],
                        "choice": preferred_choice(supplied),
                    }
                    if "appraisal_context" in supplied
                    else {"appraisal": "Get comfortable."}
                ),
                "candidates": motivated_candidates(
                    {
                        "CONTINUE": {
                            "intention": self.intention,
                            "preconditions": [],
                            "reconsider_if": "The bench is unavailable.",
                            "goal_alignment": "supports",
                            "goal_quote": supplied["authored_goal"],
                        },
                        "DEFER": {
                            "intention": "Keep standing quietly.",
                            "preconditions": [],
                            "reconsider_if": "My circumstances change.",
                        },
                    },
                    enabled="motivation_context" in supplied,
                ),
            }
        )


@pytest.mark.parametrize("mode", ["off", "shadow", "live"])
async def test_uncommanded_action_is_saved_without_moving_or_speaking_for_player(monkeypatch, mode):
    roles = AutonomousRoles()
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        _, user, avatar, state = await seed(monkeypatch, db, roles=roles)
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(
                settings=Settings(mode=mode, actor_ids=["LINA"], failure_policy="strict")
            ).model_dump(),
        }
        await db.commit()
        original = deepcopy((avatar.inventory, avatar.equipment, state.current_scene_id))
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "I wait and watch."
            )
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        await db.refresh(avatar)
        assert (avatar.inventory, avatar.equipment, state.current_scene_id) == original
        assert state.entity_states["LINA"]["visual_profile"]["worn"] == []
        placed = state.entity_states[props.KEY]["items"]
        assert [
            (entry["item_id"], entry["owner_id"], entry["spatial_position"]) for entry in placed
        ] == [("COAT", "LINA", "on the bench")]
        # Live Personality replaces the social hint; neither path adds an approval request.
        assert len(roles.calls) == (2 if mode == "live" else 3)
        stored = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == state.session_id,
                ChatMessage.role == "assistant",
                ChatMessage.content == TEXT,
            )
        )
        assert stored is not None and "Lina:" not in stored.content
        if mode == "off":
            assert roles.phases == [] and not load(state).actors
        if mode == "live":
            chosen = load(state).actors["LINA"]
            assert chosen.spoken_evidence == "" and chosen.action_evidence == ACTION["evidence"]
            assert roles.phases == ["perception", "proposal", "validation"]
            assert any(
                source.kind == "narration" and source.text == ACTION["evidence"]
                for source in load(state).minds["LINA"].sources.values()
            )


@pytest.mark.parametrize("mode", ["off", "live"])
@pytest.mark.parametrize("locked", [False, True])
async def test_autonomous_departure_uses_access_rules_and_never_takes_player_along(
    monkeypatch, mode, locked
):
    text = "Lina walks through the door into the annex."
    roles = AutonomousRoles()
    roles.actions = []
    roles.staging = {"changes": [], "props": [], "explicit": []}
    roles.intention = "Walk to the accessible annex on my own."
    roles.movements = [
        {
            "actor_id": "LINA",
            "destination_scene_id": "ANNEX",
            "presence": "present",
            "basis": "completed",
            "evidence": text,
        }
    ]
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        _, user, avatar, state = await seed(monkeypatch, db, roles=roles)
        monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", text)
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.id == "LINA"
            )
        )
        npc.moveable = True
        db.add_all(
            [
                WorldScene(
                    id="ANNEX",
                    session_id=state.session_id,
                    label="Annex",
                    description="An adjoining room.",
                ),
                WorldExit(
                    session_id=state.session_id,
                    from_scene_id=state.current_scene_id,
                    to_scene_id="ANNEX",
                    label="Annex door",
                    exit_type="bidirectional",
                    is_locked=locked,
                ),
            ]
        )
        state.entity_states = {
            **state.entity_states,
            KEY: KernelState(
                settings=Settings(mode=mode, actor_ids=["LINA"], failure_policy="strict")
            ).model_dump(),
        }
        await db.commit()
        origin = state.current_scene_id
        inventory = deepcopy(avatar.inventory)
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "I wait and watch."
            )
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        await db.refresh(avatar)
        destination = state.entity_states.get("LINA", {}).get(
            "current_scene_id", npc.current_scene_id
        )
        assert destination == (origin if locked else "ANNEX")
        assert state.current_scene_id == origin and avatar.inventory == inventory
        assert len(roles.calls) == (2 if mode == "live" else 3)
        reply = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == state.session_id,
                ChatMessage.role == "assistant",
                ChatMessage.content == text,
            )
        )
        assert reply is not None
        movement = state.entity_states[ITEMS_KEY]["movement_check"]
        assert (movement["message_id"], movement["revision_id"]) == (reply.id, reply.revision_id)
        assert [(row["actor_id"], row["status"]) for row in movement["outcomes"]] == [
            ("LINA", "blocked" if locked else "applied")
        ]
        # Legacy turn success reports processing, not certification of every prose claim.
        # The existing fail-safe must expose a rejected move and retain its qualification.
        warnings = [
            event
            for event in events
            if event.startswith("event: system") and "narrated movements need review" in event
        ]
        assert bool(warnings) is locked
        assert bool(movement["rejected"]) is locked
        assert bool(movement["accepted"]) is not locked
        if mode == "live":
            saved = load(state)
            decision = saved.actors["LINA"]
            mind = saved.minds["LINA"]
            action = next(source for source in mind.sources.values() if source.kind == "narration")
            # The original transcript survives even when the canonical move is blocked.
            assert action.text == text
            assert [entry.status for entry in action.movement_outcomes] == [
                "blocked" if locked else "applied"
            ]
            following = decision.observation.model_copy(update={"message_id": "next-input"})
            prior = previous_context(mind, decision, following)
            assert prior is not None and prior.action_evidence == text
            assert prior.movement_outcomes == action.movement_outcomes
