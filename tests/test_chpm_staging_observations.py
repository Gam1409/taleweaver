"""Confirmed staging reaches NPC cognition with current presence and item privacy."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from backend.engine.chpm import continuation, host_adapter, inference, rendering
from backend.engine.chpm.host_observation_contracts import HostFacts
from backend.engine.chpm.schema import KernelState, Perception, Settings
from backend.engine.chpm.state import KEY as CHPM_KEY
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.schema import SharedItemExtraction
from backend.engine.scene_continuity.scope import SceneScope
from backend.engine.scene_staging import props
from backend.engine.scene_staging.npc import observations
from backend.engine.scene_staging.provenance import stamp
from backend.engine.scene_staging.schema import SceneExtraction
from backend.engine.scene_staging.state import KEY, reconcile
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_state import mind
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import ACTION, install_roles, seed_vn


def person(identifier, *, inventory=None, position=None):
    return SimpleNamespace(
        id=identifier,
        name=identifier,
        entity_type="NPC",
        current_scene_id="room",
        spatial_position=position,
        inventory=inventory or [],
        equipment={},
        visual_profile={"worn": []},
        metadata_json={},
        is_hidden=False,
        is_defeated=False,
    )


def fixture():
    actor, other = person("npc"), person("other")
    player = person(
        "hero",
        inventory=[{"id": "PEN", "name": "Brass pen"}, {"id": "NOTE", "name": "Secret note"}],
    )
    state = SimpleNamespace(current_scene_id="room", entity_states={})
    write_settings(state, VnSettings(scene_staging=True))
    cast = [{"id": row.id, "position": row.spatial_position} for row in (actor, other, player)]
    text = "NPC sits on the bench. Other stands near the door."
    state.entity_states[KEY] = reconcile(
        state,
        cast,
        text,
        SceneExtraction(
            changes=[
                {
                    "entity_id": "npc",
                    "posture": "sitting",
                    "placement": {
                        "relation": "on",
                        "target_kind": "scene_object",
                        "target": "bench",
                    },
                    "evidence": "NPC sits on the bench.",
                },
                {
                    "entity_id": "other",
                    "posture": "standing",
                    "evidence": "Other stands near the door.",
                },
            ]
        ),
    )
    stamp(state, SimpleNamespace(id="old-reply", revision_id="revision", content=text))
    state.entity_states[props.KEY] = {
        "items": [
            {
                "item_id": "PEN",
                "owner_id": "hero",
                "name": "Brass pen",
                "spatial_position": "on the table",
                "status": "confirmed",
                "scene_id": "room",
                "visibility": "public",
                "source_message_id": "old-reply",
            },
            {
                "item_id": "NOTE",
                "owner_id": "hero",
                "name": "Secret note",
                "spatial_position": "inside the pocket",
                "status": "confirmed",
                "scene_id": "room",
                "source_message_id": "old-reply",
            },
        ]
    }
    manager = SimpleNamespace(
        game_id="session",
        state=state,
        avatar=player,
        _scene_continuity_scope=SceneScope(
            "room",
            frozenset({"room", "npc", "other", "__player__"}),
            "A quiet room.",
            (actor, other),
        ),
    )
    return manager, actor, other


async def test_current_pose_and_public_placed_item_reach_saved_cognitive_frame(monkeypatch):
    monkeypatch.setattr(
        host_adapter.host_sources, "reconcile", AsyncMock(side_effect=lambda manager, value: value)
    )
    manager, actor, _other = fixture()
    turn = SimpleNamespace(
        initial=KernelState(minds={"npc": mind()}),
        minds={},
        present_names={"npc": "NPC", "other": "Other"},
        perceptions={"npc": Perception(actor_id="npc", quotes=[])},
    )
    observed = SimpleNamespace(
        session_id="session",
        scene_id="room",
        message_id="input",
        revision_id=None,
        content_hash="hash",
        minute=1,
    )
    saved = await host_adapter.prepare(manager, turn, actor, observed)
    frame = next(entry for entry in saved.sources.values() if entry.kind == "host_frame")
    data = json.loads(frame.text)
    assert {row["entity_id"]: row["posture"] for row in data["character_poses"]} == {
        "npc": "sitting",
        "other": "standing",
    }
    assert data["character_poses"][0]["placement"]["target"] == "bench"
    assert [row["item_id"] for row in data["placed_items"]] == ["PEN"]
    assert "Secret note" not in frame.text and "inside the pocket" not in frame.text
    assert HostFacts.model_validate_json(frame.facts.model_dump_json()) == frame.facts


def test_simplified_fallback_has_the_same_current_staging_and_private_items_stay_private():
    manager, actor, other = fixture()
    result = continuation.identities(manager, KernelState(), [actor, other])
    current = result["npc"]["current_host_state"]
    assert current["character_poses"][0]["posture"] == "sitting"
    assert [row["item_id"] for row in current["placed_items"]] == ["PEN"]
    assert "NOTE" not in json.dumps(result)


def test_other_npcs_legacy_private_placement_is_not_public():
    manager, _actor, _other = fixture()
    items = props.candidates(manager.avatar, [], manager.state, set())
    observed = props.project(manager.state, items, observer_id="npc")
    owned = props.project(manager.state, items, observer_id="hero")
    assert [row["item_id"] for row in observed] == ["PEN"]
    assert {row["item_id"] for row in owned} == {"PEN", "NOTE"}


def test_projection_uses_current_names_and_does_not_copy_private_metadata():
    manager, _actor, _other = fixture()
    items = [
        {
            "item_id": "PEN",
            "owner_id": "hero",
            "name": "Renamed brass pen",
            "private_note": "SECRET",
        }
    ]
    projected = props.project(manager.state, items, observer_id="npc")
    assert projected[0]["name"] == "Renamed brass pen"
    assert "SECRET" not in json.dumps(projected)
    manager.state.entity_states[props.KEY]["items"][0]["owner_id"] = "other"
    assert props.project(manager.state, items, observer_id="npc") == []


def test_large_placed_item_projection_declares_omissions_and_preserves_the_ledger():
    manager, _actor, _other = fixture()
    items = [{"item_id": f"item-{i}", "owner_id": "hero", "name": f"Item {i}"} for i in range(257)]
    manager.state.entity_states[props.KEY] = {
        "items": [
            {
                **row,
                "spatial_position": "on the table",
                "status": "confirmed",
                "scene_id": "room",
                "visibility": "public",
            }
            for row in items
        ]
    }
    poses, placed, omitted = observations(manager.state, [], items, "npc", "hero")
    facts = HostFacts(
        scene_id="room", character_poses=poses, placed_items=placed, staging_omissions=omitted
    )
    assert len(facts.placed_items) == 256
    assert facts.staging_omissions == {"placed_items": 1}
    assert len(manager.state.entity_states[props.KEY]["items"]) == 257
    assert HostFacts.model_validate_json(facts.model_dump_json()) == facts


def test_changed_room_and_character_position_do_not_reuse_old_poses():
    manager, _actor, _other = fixture()
    manager.state.current_scene_id = "street"
    result = continuation.identities(manager, KernelState(), [])
    assert result == {}
    poses, placed, _ = observations(manager.state, [{"id": "npc"}], [], "npc", "hero")
    assert poses is None and placed == ()
    manager.state.current_scene_id = "room"
    poses, _, _ = observations(
        manager.state, [{"id": "npc", "position": "by the window"}], [], "npc", "hero"
    )
    assert poses == ()


def test_one_corrupt_legacy_pose_does_not_hide_other_confirmed_poses():
    manager, _actor, _other = fixture()
    manager.state.entity_states[KEY]["actors"]["npc"]["posture"] = "broken"
    poses, _, _ = observations(manager.state, [{"id": "npc"}, {"id": "other"}], [], "npc", "hero")
    assert poses is not None
    assert [(row.entity_id, row.posture) for row in poses] == [("other", "standing")]
    assert manager.state.entity_states[KEY]["actors"]["npc"]["posture"] == "broken"


async def test_real_turn_carries_saved_pose_without_an_extra_extraction_request(monkeypatch):
    class Roles(ChpmRoles):
        async def structured(self, *args, **kwargs):
            schema = kwargs.get("response_model") or args[2]
            if schema is SharedItemExtraction:
                self.calls.append((schema.__name__, args, kwargs))
                return SharedItemExtraction(staging={"changes": [], "props": [], "explicit": []})
            return await super().structured(*args, **kwargs)

    roles = Roles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        user, avatar, state, prior_id = await seed_vn(db)
        previous = await db.scalar(select(ChatMessage).where(ChatMessage.id == prior_id))
        previous.content = "Lina sits on the bench."
        write_settings(state, VnSettings(scene_staging=True))
        state.entity_states[KEY] = reconcile(
            state,
            [{"id": avatar.id}, {"id": "LINA"}],
            previous.content,
            SceneExtraction(
                changes=[{"entity_id": "LINA", "posture": "sitting", "evidence": previous.content}]
            ),
        )
        stamp(state, previous)
        state.entity_states = {
            **state.entity_states,
            CHPM_KEY: KernelState(
                settings=Settings(mode="live", actor_ids=["LINA"], failure_policy="strict")
            ).model_dump(),
        }
        await db.commit()
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(ACTION)
        ]
        assert not any(event.startswith("event: error") for event in events), "".join(events)
        assert roles.chpm_calls == ["perception", "proposal", "validation"]
        frame = json.loads(
            roles.proposal_inputs[0]["psychological_state"]["current_host_observations"][0]["text"]
        )
        assert frame["character_poses"][0]["entity_id"] == "LINA"
        assert frame["character_poses"][0]["posture"] == "sitting"
        assert sum(call[0] == "SharedItemExtraction" for call in roles.calls) == 1
        assert not any(call[0] == "SceneExtraction" for call in roles.calls)
