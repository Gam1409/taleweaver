"""Session duplication rebinds player-relative staging through normal entry points."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.sessions import copy_session
from backend.core.config import settings
from backend.engine.chpm.observable_state import capture as capture_views
from backend.engine.clothing.context import actor_records
from backend.engine.clothing.visuals import session_objects
from backend.engine.export_archives import pack_export_ads
from backend.engine.npc_actions.contracts import Approach
from backend.engine.npc_actions.preparation import capture
from backend.engine.npc_actions.publication import publish
from backend.engine.npc_actions.settings import configure
from backend.engine.scene_staging import props
from backend.engine.scene_staging.commands import CommandProof, apply_command
from backend.engine.scene_staging.provenance import remap_actor
from backend.engine.scene_staging.schema import Placement
from backend.engine.scene_staging.shared import _cast
from backend.engine.scene_staging.state import KEY, project
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.models.avatar import Avatar
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from tests.conftest import TestSessionLocal
from tests.test_legacy_session_bundle import bundle as legacy_bundle
from tests.test_npc_action_publication import fixture

bundle = legacy_bundle


@pytest.mark.parametrize("operation", ["copy", "ads"])
@pytest.mark.parametrize("nullable_audit", [False, True])
async def test_command_approach_to_player_survives_normal_session_duplication(
    operation, nullable_audit, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    async with TestSessionLocal() as db:
        host, observed, _ = await fixture(db)
        host.state.entity_states = configure(host.state.entity_states, enabled=True)
        views = await capture_views(host, ["LINA"], observed)
        draft = (await capture(host, views, observed))["LINA"]
        request = Approach(tool="approach", target_id="@player", mode="crawl")
        assert draft.execute(request)["status"] == "staged"
        draft.approved = True
        assert (await publish(host, draft))[0]["status"] == "applied"
        if nullable_audit:
            states = deepcopy(host.state.entity_states)
            states[KEY].update(explicit=None, rejected_command_pose_changes=None)
            host.state.entity_states = states
        await db.commit()
        rows = await session_objects(db, host.game_id)
        before = project(host.state, _cast(host, actor_records(host, rows), rows))["LINA"]
        source = deepcopy(host.state.entity_states[KEY]["actors"]["LINA"]["placement"])
        previous_player = host.avatar.id
        user = await db.get(User, host.state.user_id)
        if operation == "copy":
            target = (await copy_session(host.game_id, db, user))["game_id"]
        else:
            manifest = await SessionExporter.build_session_manifest(db, host.game_id)
            target = await SessionImporter.import_ads(
                db, pack_export_ads(manifest, host.game_id), user.id
            )
        game = await db.get(GameSession, target)
        state = await db.scalar(select(SessionState).where(SessionState.session_id == target))
        avatar = await db.get(Avatar, game.avatar_id)
        current = SimpleNamespace(db=db, game_id=target, state=state, avatar=avatar)
        rows = await session_objects(db, target)
        after = project(state, _cast(current, actor_records(current, rows), rows))["LINA"]

        assert avatar.id != previous_player
        assert after == {**before, "placement": {**before["placement"], "target": avatar.id}}
        placement = state.entity_states[KEY]["actors"]["LINA"]["placement"]
        assert placement["source_hash"] == source["source_hash"]
        assert placement["command_id"] == source["command_id"]
        assert placement["source_message_id"] != source["source_message_id"]
        command = state.entity_states[KEY]["actors"]["LINA"]["command"]
        assert command["requested_placement"]["target"] == avatar.id
        original = host.state.entity_states[KEY]["actors"]["LINA"]["placement"]
        assert original == source
        if nullable_audit:
            assert state.entity_states[KEY]["rejected_command_pose_changes"] is None


@pytest.mark.parametrize("identity_location", ["avatar", "state"])
async def test_legacy_bundle_rebinds_command_placement_to_its_new_player(
    auth_client, bundle, identity_location
):
    old_player = "old-player"
    if identity_location == "avatar":
        bundle["avatar"]["id"] = old_player
    else:
        bundle["game_state"]["avatar_id"] = old_player
    bundle["game_state"]["entity_states"] = apply_command(
        configure({}, enabled=True),
        scene_id="ROOM",
        cast=[{"id": old_player}, {"id": "GUIDE"}],
        actor_id="GUIDE",
        proof=CommandProof(
            command_id="prior-approach",
            actor_id="GUIDE",
            scene_id="ROOM",
            input_id="old-message",
            request_hash="b" * 64,
            operation="approach",
        ),
        enabled=True,
        posture="standing",
        placement=Placement(relation="near", target_kind="character", target=old_player),
    )

    response = await auth_client.post("/api/adventures/import/session-bundle", json=bundle)

    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        game = await db.scalar(
            select(GameSession).where(GameSession.template_id == response.json()["adventure_id"])
        )
        state = await db.scalar(select(SessionState).where(SessionState.session_id == game.id))
        assert game.avatar_id != old_player
        assert project(state, [{"id": game.avatar_id}, {"id": "GUIDE"}])["GUIDE"] == {
            "posture": "standing",
            "placement": {
                "relation": "near",
                "target_kind": "character",
                "target": game.avatar_id,
            },
        }


def test_player_rebinding_changes_only_owned_staging_identity_references():
    previous, current = "old-player", "new-player"
    raw = {
        KEY: {
            "scene_id": previous,
            "actors": {
                previous: {
                    "origin": previous,
                    "posture": {
                        "value": "sitting",
                        "command_actor_id": previous,
                        "source_message_id": previous,
                        "evidence": previous,
                    },
                },
                "NPC": {
                    "placement": {
                        "target_kind": "character",
                        "target": previous,
                        "cause": {"performer_id": previous, "source_hash": "a" * 64},
                    },
                    "command": {
                        "command_actor_id": "NPC",
                        "command_id": previous,
                        "source_hash": "b" * 64,
                        "requested_placement": {"target_kind": "character", "target": previous},
                    },
                },
                "OTHER": {"placement": {"target_kind": "scene_object", "target": previous}},
            },
            "explicit": [{"participants": [previous, "NPC"], "evidence": previous}],
            "unconfirmed_actors": [previous, "OTHER"],
            "invalidated_placements": [previous],
            "command_protected_fields": {previous: ["posture"]},
            "rejected_command_pose_changes": [{"actor_id": previous}],
        },
        props.KEY: {
            "items": [{"owner_id": previous, "item_id": previous, "spatial_position": previous}]
        },
        "__future_registry__": {"actor_id": previous},
    }
    before = deepcopy(raw)

    changed = remap_actor(raw, previous, current)

    assert raw == before and changed == remap_actor(changed, previous, current)
    data = changed[KEY]
    assert previous not in data["actors"]
    assert data["actors"][current]["posture"] == {
        **before[KEY]["actors"][previous]["posture"],
        "command_actor_id": current,
    }
    assert data["actors"][current]["origin"] == previous
    placement = data["actors"]["NPC"]["placement"]
    assert placement["target"] == placement["cause"]["performer_id"] == current
    command = data["actors"]["NPC"]["command"]
    assert command["requested_placement"]["target"] == current
    assert command["command_id"] == previous and command["source_hash"] == "b" * 64
    assert data["actors"]["OTHER"] == before[KEY]["actors"]["OTHER"]
    assert data["explicit"] == [{"participants": [current, "NPC"], "evidence": previous}]
    assert data["unconfirmed_actors"] == [current, "OTHER"]
    assert data["invalidated_placements"] == [current]
    assert data["command_protected_fields"] == {current: ["posture"]}
    assert data["rejected_command_pose_changes"] == [{"actor_id": current}]
    assert data["scene_id"] == previous
    assert changed[props.KEY]["items"] == [{**before[props.KEY]["items"][0], "owner_id": current}]
    assert changed["__future_registry__"] == before["__future_registry__"]


@pytest.mark.parametrize("previous", [None, "", 12, "new-player"])
def test_missing_or_unchanged_player_identity_preserves_staging(previous):
    raw = {KEY: {"actors": {"old-player": {"posture": {"value": "sitting"}}}}}

    assert remap_actor(raw, previous, "new-player") == raw


def test_player_rebinding_rejects_collision_without_overwriting_either_actor():
    raw = {KEY: {"actors": {"old-player": {}, "new-player": {}}}}
    before = deepcopy(raw)

    with pytest.raises(ValueError, match="cannot be merged"):
        remap_actor(raw, "old-player", "new-player")

    assert raw == before


@pytest.mark.parametrize(
    "registry,field",
    [(KEY, "explicit"), (KEY, "rejected_command_pose_changes"), (props.KEY, "items")],
)
@pytest.mark.parametrize("null_value", [False, True])
def test_player_rebinding_preserves_missing_or_null_ancillary_fields(registry, field, null_value):
    raw = {
        KEY: {"actors": {"old-player": {"posture": {"value": "sitting"}}}},
        props.KEY: {},
        "__future_registry__": {"actor_id": "old-player"},
    }
    if null_value:
        raw[registry][field] = None
    before = deepcopy(raw)
    expected = deepcopy(raw)
    expected[KEY]["actors"]["new-player"] = expected[KEY]["actors"].pop("old-player")

    assert remap_actor(raw, "old-player", "new-player") == expected
    assert raw == before


def test_player_rebinding_rejects_protected_field_collision_without_losing_either_entry():
    raw = {
        KEY: {
            "actors": {"NPC": {"posture": {"value": "sitting"}}},
            "command_protected_fields": {"old-player": ["posture"], "new-player": ["placement"]},
        }
    }
    before = deepcopy(raw)

    with pytest.raises(ValueError, match="protected fields cannot be merged"):
        remap_actor(raw, "old-player", "new-player")

    assert raw == before
