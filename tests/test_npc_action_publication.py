"""Real storage checks for ordered command publication, conflicts and current-state handoff."""

from hashlib import sha256
from types import SimpleNamespace

from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.chpm.schema import Observation
from backend.engine.clothing.visuals import session_objects
from backend.engine.npc_actions.contracts import ChangeState, Give, PutDown, Take
from backend.engine.npc_actions.preparation import capture
from backend.engine.npc_actions.publication import publish
from backend.engine.physical_conditions.ledger import read
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn


async def fixture(db):
    _, avatar, state, _ = await seed_vn(db)
    db.add_all(
        [
            WorldEntity(
                id="SECOND",
                session_id=state.session_id,
                entity_type="NPC",
                name="Second observer",
                description="A visitor.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
            ),
            WorldEntity(
                id="KEY",
                session_id=state.session_id,
                entity_type="OBJECT",
                name="A key",
                description="An old key.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
                is_portable=True,
            ),
        ]
    )
    message = ChatMessage(
        session_id=state.session_id,
        role="user",
        content="The visitors consider their next actions.",
        scene_id="START",
    )
    db.add(message)
    await db.commit()
    host = SimpleNamespace(
        db=db,
        game_id=state.session_id,
        state=state,
        avatar=avatar,
        _vn_player_message_id=message.id,
    )
    observation = Observation(
        session_id=state.session_id,
        message_id=message.id,
        revision_id=message.revision_id,
        content_hash=sha256(message.content.encode()).hexdigest(),
        sequence=0,
        scene_id="START",
        minute=0,
        player_request=message.content,
    )
    views = await capture_views(host, ["LINA", "SECOND"], observation)
    return host, observation, await capture(host, views, observation)


async def test_chained_take_property_and_give_save_one_identity_and_the_latest_property():
    async with TestSessionLocal() as db:
        host, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        requests = [
            Take(tool="take_item", item_id="KEY"),
            ChangeState(
                tool="change_item_state",
                item_id="KEY",
                dimension="surface",
                detail="A scratched handle.",
            ),
            Give(tool="give_item", item_id="KEY", recipient_id="SECOND"),
        ]
        for request in requests:
            assert draft.execute(request)["status"] == "staged"
        draft.approved = True
        before_time = host.state.in_game_time
        results = await publish(host, draft)
        assert [result["status"] for result in results] == ["applied"] * 3
        assert await publish(host, draft) == results
        await db.commit()
        snapshot = possession_snapshot(host, await session_objects(db, host.game_id))
        assert snapshot.owners["KEY"] == "SECOND"
        condition = next(
            row
            for row in read(host.state.entity_states).conditions.values()
            if row.target_id == "KEY"
        )
        assert condition.detail == "A scratched handle." and condition.latest.kind == "command"
        assert condition.latest.command.actor_id == "LINA"
        assert host.state.in_game_time == before_time


async def test_competing_plans_do_not_duplicate_an_item_and_stop_failed_dependencies():
    async with TestSessionLocal() as db:
        host, _, drafts = await fixture(db)
        first, second = drafts["LINA"], drafts["SECOND"]
        assert first.execute(Take(tool="take_item", item_id="KEY"))["status"] == "staged"
        assert second.execute(Take(tool="take_item", item_id="KEY"))["status"] == "staged"
        assert (
            second.execute(Give(tool="give_item", item_id="KEY", recipient_id="@player"))["status"]
            == "staged"
        )
        first.approved = second.approved = True
        assert (await publish(host, first))[0]["status"] == "applied"
        assert [row["status"] for row in await publish(host, second)] == [
            "blocked",
            "skipped_dependency",
        ]
        snapshot = possession_snapshot(host, await session_objects(db, host.game_id))
        assert snapshot.owners["KEY"] == "LINA"
        assert not any(
            row.get("id") == "KEY" for row in host.avatar.inventory if isinstance(row, dict)
        )


async def test_a_new_unrelated_possession_is_preserved_when_a_plan_is_revalidated():
    async with TestSessionLocal() as db:
        host, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        assert (
            draft.execute(PutDown(tool="put_down_item", item_id="HIDDEN_RING"))["status"]
            == "staged"
        )
        addition = {"id": "NEW_NOTE", "name": "New note"}
        host.state.entity_states = {
            **host.state.entity_states,
            "LINA": {"inventory": [{"id": "HIDDEN_RING", "name": "Hidden ring"}, addition]},
        }
        draft.approved = True
        assert (await publish(host, draft))[0]["status"] == "applied"
        assert addition in host.state.entity_states["LINA"]["inventory"]


async def test_an_unsubmitted_plan_and_a_changed_input_cannot_publish():
    async with TestSessionLocal() as db:
        host, _, drafts = await fixture(db)
        draft = drafts["LINA"]
        assert draft.execute(Take(tool="take_item", item_id="KEY"))["status"] == "staged"
        assert await publish(host, draft) == []
        draft.approved = True
        host._vn_player_message_id = "other-input"
        assert (await publish(host, draft))[0]["status"] == "blocked"
        assert (
            possession_snapshot(host, await session_objects(db, host.game_id)).owners["KEY"]
            == "__scene__"
        )
