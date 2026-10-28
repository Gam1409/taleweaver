"""Operational presence must agree across UI, possessions, social context and saves."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from backend.api.routes.adventures.logic import AdventureLogic
from backend.api.routes.adventures.turn_event_entities import TurnEventEntities
from backend.api.routes.adventures.turn_llm_pipeline import TurnLlmContextBuilder
from backend.engine.npc_presence import physically_present, presence, presence_context
from backend.engine.rule_engine import EntityMovement, GameEvent, WorldEntityUpdate
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.engine.visual_novel.intent import to_chat_progression_intent
from backend.engine.visual_novel.presentation import known_character
from backend.engine.visual_novel.social import _visible
from backend.models.world_entity import WorldEntity


def character(**extra):
    return SimpleNamespace(
        id="MIRA",
        name="Мира",
        entity_type="NPC",
        current_scene_id="ROOM",
        is_hidden=False,
        is_defeated=False,
        inventory=[],
        item_type=None,
        **extra,
    )


def state_for(value):
    return SimpleNamespace(
        session_id="S",
        current_scene_id="ROOM",
        entity_states={"MIRA": {"presence": value, "remembered": True}},
    )


@pytest.mark.parametrize(
    "value,expected", [("present", True), ("audible", False), ("absent", False)]
)
def test_presence_agrees_across_operational_consumers(value, expected):
    npc, state = character(), state_for(value)
    manager = SimpleNamespace(state=state, avatar=SimpleNamespace(inventory=[], equipment={}))
    assert physically_present(npc, state) is expected
    assert _visible(npc, state) is expected
    assert ("MIRA" in possession_snapshot(manager, [npc]).npcs) is expected
    builder = TurnLlmContextBuilder(manager)
    visible, hidden = builder._partition_scene_entities([npc])
    assert bool(visible) is expected
    assert not hidden  # Absence is not a discovery/stealth flag.
    assert known_character(npc, state)  # Directory remains available.
    assert f'"presence": "{value}"' in presence_context([npc], state)


def test_legacy_presence_and_unrelated_objects():
    assert presence(character()) == "present"
    assert physically_present({"entity_type": "OBJECT", "presence": "absent"})
    assert presence(character(), state_for("unknown")) == "present"


def test_vn_contract_retains_presence_and_rejects_invalid_status():
    result = to_chat_progression_intent(
        {"updated_entities": [{"entity_id": "MIRA", "presence": "audible"}]}
    )
    assert result.updated_entities[0].presence == "audible"
    with pytest.raises(ValidationError):
        WorldEntityUpdate(entity_id="MIRA", presence="left yesterday")


@pytest.mark.asyncio
async def test_presence_override_survives_reload_and_sidebar_restores(setup_test_db):
    from tests.conftest import TestSessionLocal
    from tests.test_npc_movement_and_notes import _seed_test_context

    async with TestSessionLocal() as db:
        _, _, _, state = await _seed_test_context(db)
        applier = TurnEventEntities()
        overrides = dict(state.entity_states or {})
        original = await AdventureLogic.build_session_entities(db, state)
        assert "NPC_MOV" in {entity["id"] for entity in original}
        for status in ("absent", "audible", "present"):
            update = WorldEntityUpdate(entity_id="NPC_MOV", presence=status)
            overrides.setdefault("NPC_MOV", {})
            await applier._apply_entity_description(update, overrides, "NPC_MOV")
            state.entity_states = overrides
            flag_modified(state, "entity_states")
            await db.commit()
            await db.refresh(state)
            entities = await AdventureLogic.build_session_entities(db, state)
            assert ("NPC_MOV" in {entity["id"] for entity in entities}) is (status == "present")
            npc = await db.scalar(
                select(WorldEntity).where(
                    WorldEntity.session_id == state.session_id, WorldEntity.id == "NPC_MOV"
                )
            )
            assert npc is not None  # Neither entity nor portrait is deleted.
            assert not npc.is_hidden
            overrides = dict(state.entity_states)


@pytest.mark.asyncio
async def test_real_movement_resets_previous_local_absence():
    applier = TurnEventEntities()
    applier.db = SimpleNamespace(execute=AsyncMock())
    applier.game_id = "S"
    applier._save_chat_message = AsyncMock()
    states = {"MIRA": {"presence": "absent"}}
    event = GameEvent(
        narrative_description="",
        moved_entities=[EntityMovement(entity_id="MIRA", to_scene_id="HALL")],
    )
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None))
    with patch.object(applier.db, "execute", AsyncMock(return_value=result)):
        await applier._apply_entity_movements(event, states, [])
    assert states["MIRA"]["presence"] == "present"
    assert states["MIRA"]["current_scene_id"] == "HALL"


@pytest.mark.asyncio
async def test_same_room_departure_reaches_narrator_and_state_stream(setup_test_db, monkeypatch):
    import json
    from unittest.mock import MagicMock

    from backend.api.routes.adventures.gameplay_logic import GameTurnManager
    from backend.engine.rule_engine import AdventureGeneratorToolIntent
    from backend.models.world_entity import WorldScene
    from tests.conftest import TestSessionLocal
    from tests.llm_fakes import RoleLLMFactory
    from tests.test_game_loop import _llm_call_text, _seed_game_context

    async with TestSessionLocal() as db:
        user, adventure, _, state = await _seed_game_context(db)
        adventure.strict_rules = False
        adventure.rule_enforcement_mode = "chat"
        adventure.time_per_turn = 0
        db.add(
            WorldScene(id="START", session_id=state.session_id, label="Room", description="A room.")
        )
        db.add(
            WorldEntity(
                id="MIRA",
                session_id=state.session_id,
                entity_type="NPC",
                name="Мира",
                description="A nurse.",
                current_scene_id="START",
                is_hidden=False,
            )
        )
        await db.commit()
        llm = MagicMock()
        llm.aexecute_complex_task = AsyncMock(
            return_value=AdventureGeneratorToolIntent(
                updated_entities=[WorldEntityUpdate(entity_id="MIRA", presence="absent")]
            )
        )

        async def stream():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="В комнате тихо."))])

        llm.stream_simple_task = AsyncMock(return_value=stream())
        monkeypatch.setattr(
            "backend.api.routes.adventures.gameplay_logic.GameMasterLLM",
            RoleLLMFactory(lambda *args, **kwargs: llm),
        )
        manager = GameTurnManager(db, state.session_id, user)
        chunks = [chunk async for chunk in manager.process_turn("Я остаюсь в комнате.")]
        assert llm.aexecute_complex_task.await_count == 1
        prompt = _llm_call_text(llm.stream_simple_task.call_args)
        assert '"presence": "absent"' in prompt
        states = [
            json.loads(chunk.split("data: ", 1)[1])
            for chunk in chunks
            if chunk.startswith("event: state\n")
        ]
        assert states
        assert all(entity["id"] != "MIRA" for entity in states[-1]["entities"])
        assert state.current_scene_id == "START"
        assert state.in_game_time == 0
