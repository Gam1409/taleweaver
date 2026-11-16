"""Neutral fixtures for observer-local item state and existing ownership projections."""

from types import SimpleNamespace

from backend.engine.chpm import host_observations, observable_state
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.host_state import Source, record
from backend.engine.physical_conditions.ledger import apply
from tests.test_chpm_host_state import mind
from tests.test_chpm_kernel import observation


def entity(identifier, *, kind="OBJECT", **changes):
    return SimpleNamespace(
        **{
            "id": identifier,
            "name": identifier,
            "entity_type": kind,
            "session_id": "session",
            "current_scene_id": "room",
            "inventory": [],
            "equipment": {},
            "metadata_json": {},
            "visual_profile": None,
            "age_years": 30,
            "description": "",
            "goal": "",
            "character": "",
            "is_hidden": False,
            "is_defeated": False,
            "is_in_inventory": False,
            "is_portable": True,
            "item_type": "ITEM",
            **changes,
        }
    )


def garment(identifier, layer=2, **changes):
    return entity(
        identifier,
        metadata_json={
            "clothing": {"layer": layer, "coverage": ["torso", "arms"], **changes},
            "script": "PRIVATE_SCRIPT_DO_NOT_DISCLOSE",
            "secret": "PRIVATE_METADATA",
        },
    )


def profile(*identifiers):
    return {
        "version": 1,
        "appearance": {"age_years": 30},
        "worn": [{"item_id": value} for value in identifiers],
    }


def world():
    rows = [
        entity(
            "npc",
            kind="NPC",
            inventory=["FLASK", "COAT", "LINING"],
            visual_profile=profile("LINING", "COAT"),
        ),
        entity(
            "other",
            kind="NPC",
            inventory=["OTHER_COAT", "OTHER_INNER", "OTHER_BAG_SECRET"],
            visual_profile=profile("OTHER_INNER", "OTHER_COAT"),
        ),
        entity("FLASK", is_in_inventory=True),
        garment("COAT"),
        garment("LINING", 1),
        garment("OTHER_COAT"),
        garment("OTHER_INNER", 1),
        entity("OTHER_BAG_SECRET", is_in_inventory=True),
        entity("PLAYER_BAG_SECRET", is_in_inventory=True),
        garment("PLAYER_COAT"),
        entity("BELL", is_portable=False),
        entity("KEY"),
        entity("HIDDEN", is_hidden=True),
        entity("AWAY", current_scene_id="elsewhere"),
        entity(
            "CHEST",
            item_type="CONTAINER",
            inventory=[{"id": "CONCEALED", "name": "Hidden"}],
            metadata_json={"locked": True},
        ),
    ]
    avatar = entity(
        "avatar",
        kind="PLAYER",
        inventory=["PLAYER_BAG_SECRET", "PLAYER_COAT"],
        visual_profile=profile("PLAYER_COAT"),
    )
    state = SimpleNamespace(
        session_id="session", current_scene_id="room", entity_states={}, in_game_time=5
    )
    return SimpleNamespace(game_id="session", avatar=avatar, state=state), rows


def proposal(target="FLASK", detail="The flask is half full.", **changes):
    return {
        "operation": "record",
        "target_id": target,
        "kind": "item_state",
        "part": "contents",
        "detail": detail,
        "evidence": detail,
        "visibility": "public",
        "visual_detail": detail,
        "visual_region": "torso",
        **changes,
    }


def save(manager, proposals, message="recorded"):
    manager.state.entity_states, accepted, errors = apply(
        manager.state.entity_states,
        proposals,
        targets={
            "npc",
            "other",
            "__player__",
            "FLASK",
            "COAT",
            "OTHER_COAT",
            "OTHER_INNER",
            "BELL",
            "KEY",
        },
        item_targets={"FLASK", "COAT", "OTHER_COAT", "OTHER_INNER", "BELL", "KEY"},
        narration=" ".join(row["evidence"] for row in proposals),
        message_id=message,
        session_id="session",
        minute=5,
    )
    assert not errors and len(accepted) == len(proposals)
    return accepted


def tools_for(manager, rows, actor="npc", observed=None):
    observed = observed or observation()
    view = observable_state.project(manager, rows, actor, observed)
    current = mind(actor)
    frame = host_observations.capture(
        manager.state,
        next(row for row in rows if row.id == actor),
        {"npc": "NPC", "other": "Other"},
    )
    current = record(
        current,
        Source(
            message_id=observed.message_id,
            revision_id=observed.revision_id,
            content_hash=observed.content_hash,
            role="user",
            speaker_id=actor,
            kind="host_frame",
            text=host_observations.frame(frame),
            facts=frame,
        ),
        minute=5,
    )
    return Tools(current, observed, {}, observable=view)
