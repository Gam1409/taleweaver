"""Current item placements preserve canonical identity, custody and source order."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
from typing import get_args

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.engine.clothing.body_schema import BodySlot
from backend.engine.narrated_items.apply import apply_actions
from backend.engine.narrated_items.observation_sources import verified_sources
from backend.engine.narrated_items.schema import ExistingItemAction, ItemAction, ItemExtraction
from backend.engine.visual_novel.continuity import Possessions
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn

SLOT = get_args(BodySlot)[0]
TEXT = "Researcher A keeps the sealed sensor secured in the assigned body slot."
ITEM = {
    "id": "SENSOR",
    "name": "Sealed sensor",
    "description": "A sealed glass sensor with a blue mark.",
    "item_type": "DEFAULT",
    "condition_note": "dry",
    "item_origin": {"kind": "runtime", "source_message_id": "original-source"},
    "extension": {"serial": "sensor-one"},
}


def state(owner="NPC_B", *, item=None):
    item = deepcopy(ITEM if item is None else item)
    actors = {}
    for identifier in ("NPC_A", "NPC_B", "NPC_C"):
        inventory = [deepcopy(item)] if identifier == owner else []
        actors[identifier] = {
            "id": identifier,
            "name": "Researcher " + identifier[-1],
            "age_years": 30,
            "inventory": inventory,
            "resolved_inventory": deepcopy(inventory),
            "equipment": {},
            "visual_profile": {
                "appearance": {"age_years": 30},
                "body": {"attachment_slots": [SLOT]},
                "worn": [],
            },
        }
    return actors, Possessions(
        items={"SENSOR": item}, owners={"SENSOR": owner}, catalog={"SENSOR": deepcopy(item)}
    )


def observation(**changes):
    return ItemAction.model_validate(
        {
            "item_id": "SENSOR",
            "source_owner": "NPC_B",
            "destination_owner": "NPC_A",
            "disposition": "worn",
            "basis": "observed_placement",
            "attachment_slot": SLOT,
            "evidence": TEXT,
            **changes,
        }
    )


def apply(proposals, actors, snapshot, *, narration=None, **options):
    return apply_actions(
        ItemExtraction(actions=proposals),
        actors,
        snapshot,
        narration or " ".join(row.evidence for row in proposals),
        detailed=True,
        session_id="SESSION",
        message_id="TURN",
        **options,
    )


def owners(actors):
    return [
        identifier
        for identifier, actor in actors.items()
        if any(row.get("id") == "SENSOR" for row in actor["inventory"])
    ]


def test_current_placement_moves_the_existing_instance_and_keeps_intrinsic_metadata():
    actors, snapshot = state()
    original = deepcopy(actors)
    changed, accepted, errors = apply([observation()], actors, snapshot)
    assert not errors and len(accepted) == 1
    assert owners(changed) == ["NPC_A"]
    assert changed["NPC_A"]["inventory"] == [ITEM]
    assert changed["NPC_B"]["resolved_inventory"] == []
    worn = changed["NPC_A"]["visual_profile"]["worn"][0]
    assert worn["item_id"] == "SENSOR" and worn["attachment_slot"] == SLOT
    assert worn["source"]["evidence"] == TEXT
    assert worn["source"]["content_hash"] == sha256(TEXT.encode()).hexdigest()
    assert actors == original and snapshot.owners == {"SENSOR": "NPC_B"}


@pytest.mark.parametrize("item_type", [None, "", "DEFAULT"])
def test_known_plain_object_legacy_types_remain_compatible(item_type):
    actors, snapshot = state(item={**ITEM, "item_type": item_type})
    changed, accepted, errors = apply([observation()], actors, snapshot)
    assert accepted and not errors and owners(changed) == ["NPC_A"]


@pytest.mark.parametrize(
    "item_change",
    [
        {"item_type": "WEAPON"},
        {"item_type": "KEY"},
        {"hp_change": 5},
        {"stat_modifier_strength": -1},
        {"wearable_slots": ["Chest"]},
        {"clothing": {}},
        {"clothing": {"category": "accessory", "layer": 0, "coverage": ["torso"]}},
    ],
)
def test_observation_cannot_move_a_mechanical_or_garment_item(item_change):
    actors, snapshot = state(item={**ITEM, **item_change})
    changed, accepted, errors = apply([observation()], actors, snapshot)
    assert errors and not accepted and changed == actors


@pytest.mark.parametrize(
    "item_change",
    [
        {"item_type": "CONSUMABLE", "hp_change": 5},
        {"clothing": {"category": "accessory", "layer": 0, "coverage": ["torso"]}},
    ],
)
def test_same_owner_observation_keeps_existing_attachment_eligibility(item_change):
    actors, snapshot = state("NPC_A", item={**ITEM, **item_change})
    changed, accepted, errors = apply([observation(source_owner="NPC_A")], actors, snapshot)
    assert accepted and not errors and owners(changed) == ["NPC_A"]


@pytest.mark.parametrize(
    "changes", [{"attachment_slot": None}, {"disposition": "held"}, {"uncovered_regions": []}]
)
def test_current_placement_schema_requires_an_explicit_body_binding(changes):
    with pytest.raises(ValidationError):
        observation(**changes)


def test_new_item_cannot_use_an_existing_placement_observation_basis():
    with pytest.raises(ValidationError):
        observation(
            item_id=None,
            new_item={"kind": "ordinary", "name": "Sensor", "description": "A sealed sensor."},
        )


def test_wire_schema_matches_the_existing_observation_contract():
    raw = observation().model_dump()
    schema = Draft202012Validator(ExistingItemAction.model_json_schema())
    assert schema.is_valid(raw)
    for change in (
        {"attachment_slot": None},
        {"disposition": "carried"},
        {"uncovered_regions": []},
    ):
        assert not schema.is_valid({**raw, **change})


def test_later_completed_removal_wins_over_an_earlier_current_observation():
    actors, snapshot = state()
    remove = observation(
        source_owner="NPC_A",
        basis="completed",
        disposition="carried",
        attachment_slot=None,
        evidence="Researcher A removes the sensor and holds it in a gloved hand.",
    )
    changed, accepted, errors = apply([observation(), remove], actors, snapshot)
    assert not errors and len(accepted) == 2
    assert owners(changed) == ["NPC_A"]
    assert changed["NPC_A"]["visual_profile"]["worn"] == []


@pytest.mark.parametrize("mechanics_applied", [False, True])
def test_completed_transfer_prefix_preserves_the_final_placement_observation(mechanics_applied):
    actors, snapshot = state("NPC_A" if mechanics_applied else "NPC_B")
    transfer = observation(
        basis="completed",
        disposition="carried",
        attachment_slot=None,
        evidence="Researcher B hands the sealed sensor to Researcher A.",
    )
    final = observation(source_owner="NPC_A")
    changed, accepted, errors = apply([transfer, final], actors, snapshot)
    assert not errors and owners(changed) == ["NPC_A"]
    assert changed["NPC_A"]["visual_profile"]["worn"][0]["attachment_slot"] == SLOT
    assert [row["action_index"] for row in accepted] == ([1] if mechanics_applied else [0, 1])


def test_resolved_transfer_prefix_does_not_replay_intermediate_carriers():
    actors, snapshot = state("NPC_A")
    first = observation(
        destination_owner="NPC_C",
        basis="completed",
        disposition="carried",
        attachment_slot=None,
        evidence="Researcher B hands the sealed sensor to Researcher C.",
    )
    second = observation(
        source_owner="NPC_C",
        basis="completed",
        disposition="carried",
        attachment_slot=None,
        evidence="Researcher C hands the sealed sensor to Researcher A.",
    )
    changed, accepted, errors = apply(
        [first, second, observation(source_owner="NPC_A")], actors, snapshot
    )
    assert not errors and [row["action_index"] for row in accepted] == [2]
    assert changed["NPC_B"] == actors["NPC_B"] and changed["NPC_C"] == actors["NPC_C"]


def test_earlier_observation_cannot_undo_a_mechanics_resolved_final_transfer():
    actors, snapshot = state("NPC_A")
    first = observation(
        source_owner="NPC_B",
        destination_owner="NPC_B",
        evidence="Researcher B keeps the sensor secured in the assigned body slot.",
    )
    final = observation(
        basis="completed",
        disposition="carried",
        attachment_slot=None,
        evidence="Researcher B then hands the sensor to Researcher A.",
    )
    changed, accepted, errors = apply([first, final], actors, snapshot)
    assert not errors and not accepted and changed == actors


def test_repeated_current_input_keeps_its_matching_proof_without_a_new_change():
    actors, snapshot = state("NPC_A")
    action = observation(source_owner="NPC_A")
    changed, accepted, errors = apply([action], actors, snapshot)
    assert accepted and not errors
    repeated, accepted, errors = apply([action], changed, snapshot)
    assert not accepted and not errors and repeated == changed


def test_valid_prior_proof_remains_a_noop_and_invalid_prior_proof_is_replaced():
    actors, snapshot = state("NPC_A")
    actors["NPC_A"]["visual_profile"]["worn"] = [
        {
            "item_id": "SENSOR",
            "attachment_slot": SLOT,
            "source": {
                "source_message_id": "older-source",
                "content_hash": "0" * 64,
                "evidence": "An earlier observation.",
            },
        }
    ]
    action = observation(source_owner="NPC_A")
    changed, accepted, errors = apply(
        [action], actors, snapshot, verified_sources={("NPC_A", "SENSOR")}
    )
    assert not accepted and not errors and changed == actors
    changed, accepted, errors = apply([action], actors, snapshot, verified_sources=set())
    assert accepted and not errors
    proof = changed["NPC_A"]["visual_profile"]["worn"][0]["source"]
    assert (
        proof["request_id"] == "TURN" and proof["content_hash"] == sha256(TEXT.encode()).hexdigest()
    )


def test_existing_completed_transfer_still_works_and_observed_wear_cannot_steal():
    actors, snapshot = state()
    completed = observation(basis="completed")
    changed, accepted, errors = apply([completed], actors, snapshot)
    assert accepted and not errors and owners(changed) == ["NPC_A"]
    legacy = observation(basis="observed_wear")
    changed, accepted, errors = apply([legacy], actors, snapshot)
    assert errors and not accepted and changed == actors


@pytest.mark.parametrize(
    "text",
    [
        "The sensor's blue mark caught the light; Researcher A still bore it in the assigned slot.",
        "While Researcher A worked, the sealed sensor remained secured in the assigned body slot.",
        "The sealed sensor was already in Researcher A's assigned slot when the lamps dimmed.",
    ],
)
def test_current_observation_does_not_require_a_placement_verb(text):
    actors, snapshot = state()
    changed, accepted, errors = apply([observation(evidence=text)], actors, snapshot)
    assert accepted and not errors and owners(changed) == ["NPC_A"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["assistant", "user", "edited", "missing", "foreign", "role", "debug"]
)
async def test_saved_proof_lookup_checks_its_actual_source_and_session(setup_test_db, kind):
    actors, _ = state("NPC_A")
    previous = "Researcher A keeps the sensor in the assigned slot."
    source_role = "user" if kind == "user" else "assistant"
    actors["NPC_A"]["visual_profile"]["worn"] = [
        {
            "item_id": "SENSOR",
            "attachment_slot": SLOT,
            "source": {
                "source_message_id": "placement-source",
                "source_role": source_role,
                "content_hash": sha256(previous.encode()).hexdigest(),
                "evidence": previous,
            },
        }
    ]
    async with TestSessionLocal() as db:
        user, _avatar, game_state, _source_id = await seed_vn(db)
        session_id = game_state.session_id
        if kind == "foreign":
            db.add(
                GameSession(
                    id="foreign-session",
                    user_id=user.id,
                    template_id=game_state.template_id,
                    avatar_id=game_state.avatar_id,
                )
            )
            await db.flush()
            session_id = "foreign-session"
        if kind != "missing":
            db.add(
                ChatMessage(
                    id="placement-source",
                    session_id=session_id,
                    role="user" if kind in {"user", "role"} else "assistant",
                    content="The message was rewritten." if kind == "edited" else previous,
                    is_debug=kind == "debug",
                )
            )
            await db.commit()
        manager = SimpleNamespace(db=db, state=game_state)
        result = await verified_sources(
            manager, ItemExtraction(actions=[observation(source_owner="NPC_A")]), actors
        )
        assert result == ({("NPC_A", "SENSOR")} if kind in {"assistant", "user"} else set())
