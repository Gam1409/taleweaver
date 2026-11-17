"""Scripted extraction checks owner boundaries, not the model's semantic classification."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import apply, read
from backend.engine.scene_continuity.ledger import read as scene_state
from backend.engine.scene_continuity.presentation import visual_facts
from backend.engine.scene_illustrations.snapshots import registry_of
from backend.engine.scene_staging.state import KEY as STAGING_KEY
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn

POSE = "Lina stands with her arms folded and looks toward the window."
SIGN = "Her left hand continues trembling."
ENDING = "Lina lowers both hands from above the console and folds her arms."
SEED = [
    ("other", "hand_pose", "Both hands are held above the console.", "LINA"),
    ("injury", "left_hand", "A cut remains on the left hand.", "LINA"),
    ("other", "left_hand", "The left hand is trembling.", "LINA"),
    ("contamination", "right_hand", "Mud remains on the right hand.", "LINA"),
    ("item_state", "form", "The note remains creased.", "NOTE"),
]


def body_sign(evidence=SIGN):
    return {
        "operation": "record",
        "target_id": "LINA",
        "kind": "other",
        "part": "left_hand",
        "detail": "The left hand is trembling.",
        "visibility": "public",
        "evidence": evidence,
    }


class ObservationRoles(TurnRoles):
    """Explicitly authored output keeps inference outside these integration controls."""

    def __init__(self, conditions, frame, posture=None):
        super().__init__()
        self.conditions, self.frame, self.posture = conditions, frame, posture

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if not issubclass(schema, ItemExtraction):
            return await super().structured(*args, **kwargs)
        self.calls.append((schema.__name__, args, kwargs))
        payload = json.loads(args[1])
        passages = payload["completed_narration"]
        rows = {
            "condition_updates": deepcopy(self.conditions),
            "final_frame_actions": deepcopy(self.frame),
        }
        references = _bind_rows(rows, passages)
        staging = _staging(payload, self.posture, passages)
        references["staging"] = {row["evidence"] for row in staging.get("changes", [])}
        coverage = {
            key: [domain for domain, cited in references.items() if cited.intersection(group)]
            or ["unchanged"]
            for key, group in payload["extraction_coverage_groups"].items()
        }
        return extraction(
            schema,
            **rows,
            coverage=coverage,
            **({"staging": staging} if payload["scene_staging"] is not None else {}),
        )


def _bind_rows(rows, passages):
    result = {}
    for field, domain in (("condition_updates", "conditions"), ("final_frame_actions", "scene")):
        for row in rows[field]:
            row["evidence"] = next(
                (key for key, quote in passages.items() if quote == row["evidence"]),
                row["evidence"],
            )
        result[domain] = {row["evidence"] for row in rows[field]}
    return result


def _staging(payload, posture, passages):
    if payload["scene_staging"] is None or posture is None:
        return {"changes": [], "props": [], "explicit": []}
    quote = next(iter(passages))
    return {
        "changes": [{"entity_id": "LINA", "posture": posture, "evidence": quote}],
        "props": [],
        "explicit": [],
    }


async def _seed(monkeypatch, db, roles, enabled, text):
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", text)
    install_roles(monkeypatch, roles)
    user, avatar, state, _ = await seed_vn(db)
    npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
    npc.inventory = [{"id": "NOTE", "name": "Paper note"}]
    write_settings(state, VnSettings(scene_staging=enabled))
    await db.commit()
    return user, avatar, state


async def _turn(db, user, state):
    events = [
        chunk
        async for chunk in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
    ]
    assert final_payload(events)["status"] == "success", "".join(events)
    await db.refresh(state)
    ledger = scene_state(state.entity_states)
    reply = await db.get(ChatMessage, ledger.frame_message_id)
    assert reply and reply.role == "assistant"
    return reply


async def _seed_conditions(db, state):
    text = " ".join(row[2] for row in SEED)
    message = ChatMessage(
        id="observation-seed", session_id=state.session_id, role="assistant", content=text
    )
    db.add(message)
    states, identifiers, errors = apply(
        state.entity_states,
        [
            {
                "operation": "record",
                "target_id": target,
                "kind": kind,
                "part": part,
                "detail": "creased" if kind == "item_state" else quote,
                "evidence": quote,
            }
            for kind, part, quote, target in SEED
        ],
        targets={"LINA", "NOTE"},
        item_targets={"NOTE"},
        narration=text,
        message_id=message.id,
        session_id=state.session_id,
        minute=0,
    )
    assert not errors and len(identifiers) == len(SEED)
    state.entity_states = states
    await db.commit()
    return identifiers, deepcopy(read(states).conditions)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("same_passage", [False, True])
async def test_final_frame_and_physiological_sign_share_source_without_changing_ownership(
    monkeypatch, enabled, same_passage
):
    text = (
        POSE[:-1] + " while her left hand continues trembling."
        if same_passage
        else POSE + " " + SIGN
    )
    proof = text if same_passage else SIGN
    frame = [{"actor_ids": ["LINA"], "detail": POSE, "evidence": text if same_passage else POSE}]
    roles = ObservationRoles([body_sign(proof)], frame, "standing")
    async with TestSessionLocal() as db:
        user, avatar, state = await _seed(monkeypatch, db, roles, enabled, text)
        possessions = deepcopy(avatar.inventory)
        reply = await _turn(db, user, state)
        condition = next(iter(read(state.entity_states).conditions.values()))
        assert condition.kind == "other" and condition.part == "left_hand"
        assert condition.origin.message_id == reply.id and condition.origin.quote == proof
        assert condition.origin.evidence_span.start == (0 if same_passage else len(POSE) + 1)
        action = scene_state(state.entity_states).frame_actions[0]
        assert action.detail == POSE
        if same_passage:
            assert action.evidence_span == condition.origin.evidence_span
        assert visual_facts(state, {"LINA"}, "", reply.id)["visible_action"] == POSE
        assert not visual_facts(state, {"LINA"}, "", "another-message")["visible_action"]
        assert avatar.inventory == possessions and len(roles.calls) == 3
        assert (STAGING_KEY in state.entity_states) is enabled
        if enabled:
            assert (
                state.entity_states[STAGING_KEY]["actors"]["LINA"]["posture"]["value"] == "standing"
            )
        snapshot = registry_of(state.entity_states)["snapshots"][reply.id]
        assert snapshot["visible_facts"]["visible_action"] == POSE


@pytest.mark.parametrize("enabled", [False, True])
async def test_exact_id_cleanup_preserves_independent_same_hand_and_item_facts(
    monkeypatch, enabled
):
    frame = [{"actor_ids": ["LINA"], "detail": ENDING, "evidence": ENDING}]
    roles = ObservationRoles([], frame, "standing")
    async with TestSessionLocal() as db:
        user, _, state = await _seed(monkeypatch, db, roles, enabled, ENDING)
        identifiers, before = await _seed_conditions(db, state)
        roles.conditions = [
            {"operation": "remove", "condition_id": identifiers[0], "evidence": ENDING}
        ]
        first = await _turn(db, user, state)
        ledger = read(state.entity_states)
        assert ledger.conditions[identifiers[0]].status == "resolved"
        assert ledger.conditions[identifiers[0]].origin == before[identifiers[0]].origin
        assert ledger.conditions[identifiers[0]].latest.message_id == first.id
        assert {key: row for key, row in ledger.conditions.items() if key != identifiers[0]} == {
            key: row for key, row in before.items() if key != identifiers[0]
        }
        assert not ledger.last_check["rejected"]
        roles.conditions, roles.frame, roles.posture = [], [], None
        monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", 'Lina says, "Understood."')
        second = await _turn(db, user, state)
        assert read(state.entity_states).conditions == ledger.conditions
        assert not scene_state(state.entity_states).frame_actions
        assert not visual_facts(state, {"LINA"}, "", second.id)["visible_action"]
        assert (
            registry_of(state.entity_states)["snapshots"][first.id]["visible_facts"][
                "visible_action"
            ]
            == ENDING
        )
        assert len(roles.calls) == 6


@pytest.mark.parametrize("enabled", [False, True])
async def test_a_new_pose_cannot_clear_unmentioned_conditions_on_the_same_body_part(
    monkeypatch, enabled
):
    frame = [{"actor_ids": ["LINA"], "detail": ENDING, "evidence": ENDING}]
    roles = ObservationRoles([], frame, "standing")
    async with TestSessionLocal() as db:
        user, _, state = await _seed(monkeypatch, db, roles, enabled, ENDING)
        _, before = await _seed_conditions(db, state)
        await _turn(db, user, state)
        assert read(state.entity_states).conditions == before
        assert scene_state(state.entity_states).frame_actions[0].detail == ENDING
        assert len(roles.calls) == 3


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("invalid_domain", ["conditions", "scene"])
async def test_bad_source_in_one_owner_cannot_veto_the_other(monkeypatch, enabled, invalid_domain):
    conditions = [
        body_sign("A sign absent from this narration." if invalid_domain == "conditions" else SIGN)
    ]
    frame = [
        {
            "actor_ids": ["LINA"],
            "detail": POSE,
            "evidence": "A pose absent from this narration." if invalid_domain == "scene" else POSE,
        }
    ]
    roles = ObservationRoles(conditions, frame, "standing")
    async with TestSessionLocal() as db:
        user, _, state = await _seed(monkeypatch, db, roles, enabled, POSE + " " + SIGN)
        await _turn(db, user, state)
        physical, scene = read(state.entity_states), scene_state(state.entity_states)
        assert bool(physical.conditions) is (invalid_domain != "conditions")
        assert bool(physical.last_check["rejected"]) is (invalid_domain == "conditions")
        assert bool(scene.frame_actions) is (invalid_domain != "scene")
        assert bool(scene.last_check["rejected"]) is (invalid_domain == "scene")
        assert len(roles.calls) == 3
