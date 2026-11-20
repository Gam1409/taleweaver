"""Portable VN placements require their existing saved player source during action control."""

from copy import deepcopy

import pytest

from backend.engine import turn_controls
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.engine.clothing.visuals import session_objects
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.mutation_targets import validate_mutation_targets
from backend.engine.visual_novel import player_items
from backend.engine.visual_novel.continuity import possession_snapshot, prepare_intent
from backend.engine.visual_novel.intent import progression_schema
from backend.engine.visual_novel.movement_recovery import resolve_event
from backend.engine.visual_novel.movement_sources import prepare
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn

REQUEST = "Lina, take the brass key from the table and hand it to me."
PLACEMENT = "I set the brass key on the bench."


def proof(**changes):
    return {
        "kind": "current_player_action",
        "passage_id": "player:p0",
        "basis": "resolved_external_effect",
        **changes,
    }


def current(manager, key, field="spatial_position"):
    return manager.state.entity_states.get(key.id, {}).get(field, getattr(key, field))


async def setup(db, *, text=REQUEST, settings=None, portable=True):
    user, avatar, state, _ = await seed_vn(db)
    selected = Settings(
        mode="live",
        workflow="integrated",
        action_tools=True,
        actor_ids=["LINA"],
        agent_steps=1,
    )
    if settings is not None:
        selected = Settings.model_validate({**selected.model_dump(), **settings})
    state.entity_states = {**state.entity_states, KEY: KernelState(settings=selected).model_dump()}
    key = WorldEntity(
        id="BRASS_KEY",
        session_id=state.session_id,
        entity_type="OBJECT",
        name="Brass key",
        description="An ordinary brass key.",
        spatial_position="on the table",
        current_scene_id="START",
        is_portable=portable,
        is_hidden=False,
        is_in_inventory=False,
    )
    request = ChatMessage(session_id=state.session_id, role="user", content=text, scene_id="START")
    db.add_all(
        [
            key,
            request,
            WorldScene(
                id="ANNEX", session_id=state.session_id, label="Annex", description="A room."
            ),
        ]
    )
    await db.commit()
    manager = GameTurnManager(db, state.session_id, user, state=state, avatar=avatar)
    assert await manager.initialize()
    manager._vn_player_message_id = request.id
    turn_controls.bind_input(manager, request)
    await prepare(manager)
    return manager, key, request


def placement(*, source=None, field="updated_entities", entity_id="BRASS_KEY"):
    binding = {"movement_source": source} if source is not None else {}
    update = {"entity_id": entity_id, "notes": "Retain this independent note."}
    if field == "updated_entities":
        update.update(spatial_position="in Lina's hand", **binding)
        return {field: [update]}
    return {
        "updated_entities": [update],
        "moved_entities": [
            {
                "entity_id": entity_id,
                "to_spatial_position": "in Lina's hand",
                "to_scene_id": "ANNEX",
                **binding,
            }
        ],
    }


async def apply(manager, raw, *, mutate=None):
    rows = await session_objects(manager.db, manager.game_id)
    proposal = progression_schema(manager.state).model_validate(raw)
    manager._vn_movement_proposal = proposal.model_copy(deep=True)
    captured = turn_controls.scope(manager, "preliminary_items")
    plan = await player_items.prepare(
        manager, proposal, rows, scope=player_items.capture(manager), captured=captured
    )
    intent = prepare_intent(manager, proposal, rows, control=captured, item_plan=plan)
    event = manager._build_progression_event(intent)
    player_items.attach(event, plan)
    assert "movement_source" not in event.model_dump_json()
    if mutate is not None:
        mutate(event)
    await validate_mutation_targets(manager, event)
    notices = await resolve_event(manager, event)
    await manager._apply_game_event(event)
    await manager.db.commit()
    return event, notices


@pytest.mark.parametrize("field", ["updated_entities", "moved_entities"])
async def test_saved_npc_request_cannot_preapply_the_live_unproven_key_placement(field):
    async with TestSessionLocal() as db:
        manager, key, _ = await setup(db)
        before_inventory = deepcopy(manager.avatar.inventory)
        _, notices = await apply(manager, placement(field=field))
        await db.refresh(key)
        assert (
            current(manager, key) == "on the table"
            and current(manager, key, "current_scene_id") == "START"
        )
        assert manager.state.entity_states["BRASS_KEY"]["notes"] == "Retain this independent note."
        snapshot = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert snapshot.owners["BRASS_KEY"] == "__scene__"
        assert manager.avatar.inventory == before_inventory and notices


@pytest.mark.parametrize(
    "source",
    [
        proof(basis="attempt"),
        proof(basis="intention"),
        proof(basis="uncertain"),
        proof(basis="completed"),
        proof(passage_id="player:p99"),
        proof(kind="previous_narration", passage_id="history:p0", basis="completed"),
        {"kind": "invalid", "passage_id": "player:p0", "basis": "resolved_external_effect"},
    ],
)
async def test_source_reference_alone_cannot_complete_an_unresolved_npc_request(source):
    async with TestSessionLocal() as db:
        manager, key, _ = await setup(db)
        _, notices = await apply(manager, placement(source=source))
        await db.refresh(key)
        assert current(manager, key) == "on the table" and notices


async def test_exact_current_player_placement_uses_the_saved_source_without_changing_custody():
    async with TestSessionLocal() as db:
        manager, key, _ = await setup(db, text=PLACEMENT)
        raw = placement(source=proof(), entity_id=" brass_key ")
        raw["updated_entities"][0]["spatial_position"] = "on the bench"
        _, notices = await apply(manager, raw)
        await db.refresh(key)
        assert key.id == "BRASS_KEY" and current(manager, key) == "on the bench" and not notices
        snapshot = possession_snapshot(manager, await session_objects(db, manager.game_id))
        assert snapshot.owners["BRASS_KEY"] == "__scene__"
        assert manager.state.current_scene_id == "START"


@pytest.mark.parametrize("changed", ["content", "revision", "role", "input", "scene"])
async def test_changed_saved_player_source_cannot_apply_a_previously_prepared_event(changed):
    async with TestSessionLocal() as db:
        manager, key, request = await setup(db, text=PLACEMENT)
        if changed == "content":
            request.content = "I stay here."
        elif changed == "revision":
            request.revision_id = "changed-revision"
        elif changed == "role":
            request.role = "assistant"
        elif changed == "input":
            manager._vn_player_message_id = "another-input"
        else:
            request.scene_id = "ANNEX"
        await db.commit()
        with pytest.raises(ValueError):
            await apply(manager, placement(source=proof()))
        await db.refresh(key)
        assert current(manager, key) == "on the table"
        assert "notes" not in manager.state.entity_states.get(key.id, {})


@pytest.mark.parametrize(
    "settings",
    [
        {"mode": "off"},
        {"mode": "shadow"},
        {"action_tools": False},
        {"action_tools": False, "workflow": "staged"},
        {"control_scope": "combat_actions"},
    ],
)
async def test_other_controller_modes_keep_existing_object_placement_behavior(settings):
    async with TestSessionLocal() as db:
        manager, key, _ = await setup(db, settings=settings)
        _, notices = await apply(manager, placement())
        await db.refresh(key)
        assert current(manager, key) == "in Lina's hand" and not notices


async def test_legacy_settings_and_fixed_objects_keep_existing_placement_behavior():
    async with TestSessionLocal() as db:
        manager, key, _ = await setup(db, portable=False)
        _, notices = await apply(manager, placement())
        await db.refresh(key)
        assert current(manager, key) == "in Lina's hand" and not notices
        key.is_portable = True
        manager.state.entity_states = {
            name: value for name, value in manager.state.entity_states.items() if name != KEY
        }
        await db.commit()
        raw = placement()
        raw["updated_entities"][0]["spatial_position"] = "on the bench"
        _, notices = await apply(manager, raw)
        await db.refresh(key)
        assert current(manager, key) == "on the bench" and not notices


async def test_mutated_placement_cannot_reuse_the_original_players_source_binding():
    async with TestSessionLocal() as db:
        manager, key, _ = await setup(db, text=PLACEMENT)

        def mutate(event):
            event.updated_entities[0].spatial_position = "under the shelf"

        _, notices = await apply(manager, placement(source=proof()), mutate=mutate)
        await db.refresh(key)
        assert current(manager, key) == "on the table" and notices


@pytest.mark.parametrize("changed", ["hidden", "elsewhere"])
async def test_current_source_does_not_make_an_unavailable_item_accessible(changed):
    async with TestSessionLocal() as db:
        manager, key, _ = await setup(db, text=PLACEMENT)
        if changed == "hidden":
            key.is_hidden = True
        else:
            key.current_scene_id = "ANNEX"
        await db.commit()
        _, notices = await apply(manager, placement(source=proof()))
        assert current(manager, key) == "on the table" and notices
