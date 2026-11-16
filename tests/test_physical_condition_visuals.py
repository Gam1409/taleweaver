"""Image visibility is explicit evidence plus current clothing, never the public flag alone."""

import json
from types import SimpleNamespace

from sqlalchemy import select

from backend.engine.physical_conditions.ledger import apply, read
from backend.engine.scene_illustrations.snapshots import registry_of
from backend.engine.scene_illustrations.visual_plan import inventory
from backend.engine.visual_novel.runtime import capture_completed_moment
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn

TEXT = "A white bandage is visible around Lina's neck."


def condition(**extra):
    return {
        "operation": "record",
        "target_id": "LINA",
        "kind": "injury",
        "part": "neck",
        "detail": "A bandaged neck wound.",
        "visibility": "public",
        "evidence": TEXT,
        "visual_detail": "A white bandage",
        "visual_region": "head",
        **extra,
    }


def saved_conditions(proposal=None):
    states, accepted, errors = apply(
        {},
        [proposal or condition()],
        targets={"LINA", "COAT", "UNDERWEAR"},
        narration=TEXT,
        message_id="source",
        session_id="session",
        minute=10,
    )
    assert accepted and not errors
    return states


def actors(covered=False):
    items = (
        [
            {
                "id": "HOOD",
                "name": "Opaque hood",
                "clothing": {
                    "category": "clothing",
                    "layer": 2,
                    "coverage": ["head"],
                    "opaque": True,
                },
            }
        ]
        if covered
        else []
    )
    return {
        "LINA": {
            "id": "LINA",
            "visual_profile": {
                "appearance": {"age_years": 25},
                "worn": [{"item_id": "HOOD"}] if covered else [],
            },
            "resolved_inventory": items,
        }
    }


async def test_snapshot_carries_a_confirmed_visible_trace_and_plan_atom():
    async with TestSessionLocal() as db:
        _, avatar, state, _ = await seed_vn(db)
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        npc.visual_profile = actors()["LINA"]["visual_profile"]
        source = ChatMessage(
            id="source", session_id=state.session_id, role="assistant", content=TEXT
        )
        reply = ChatMessage(
            id="next", session_id=state.session_id, role="assistant", content="Lina nods."
        )
        db.add_all([source, reply])
        state.entity_states = {**state.entity_states, **saved_conditions()}
        await db.flush()
        await capture_completed_moment(SimpleNamespace(db=db, state=state, avatar=avatar), reply)
        frozen = registry_of(state.entity_states)["snapshots"][reply.id]["visible_facts"]
        assert "A white bandage" in json.dumps(frozen)
        atom = next(atom for atom in inventory(frozen) if atom.predicate == "physical_condition")
        assert atom.subject == "LINA" and atom.required


def test_clothing_can_hide_a_previous_visual_trace_without_resolving_condition():
    from backend.engine.physical_conditions.visuals import project

    saved = saved_conditions()
    state = SimpleNamespace(entity_states=saved)
    assert project(state, actors(), detailed=True)
    assert not project(state, actors(covered=True), detailed=True)
    assert next(iter(read(saved).conditions.values())).status == "active"


def test_private_unknown_resolved_and_non_exact_visual_claims_are_not_images():
    from backend.engine.physical_conditions.visuals import project

    for proposal in [
        condition(visibility="private"),
        condition(visual_detail="A revealing invented injury"),
        condition(visual_detail="", visual_region=None),
    ]:
        saved = saved_conditions(proposal)
        assert not project(SimpleNamespace(entity_states=saved), actors(), detailed=True)
    saved = saved_conditions()
    unknown = actors()
    unknown["LINA"]["visual_profile"] = None
    assert not project(SimpleNamespace(entity_states=saved), unknown, detailed=True)
    identifier = next(iter(read(saved).conditions))
    saved, _, errors = apply(
        saved,
        [{"operation": "heal", "condition_id": identifier, "evidence": "The neck has healed."}],
        targets={"LINA"},
        narration="The neck has healed.",
        message_id="healed",
        session_id="session",
        minute=20,
    )
    assert not errors and not project(SimpleNamespace(entity_states=saved), actors(), detailed=True)


def test_visual_evidence_is_revoked_by_edit_without_healing_the_condition():
    from backend.engine.physical_conditions.visuals import project, retract

    current = SimpleNamespace(entity_states=saved_conditions())
    retract(current, "source")
    assert not project(current, actors(), detailed=True)
    assert next(iter(read(current.entity_states).conditions.values())).status == "active"


def test_hidden_underwear_trace_never_escapes_through_a_garment_id():
    from backend.engine.physical_conditions.visuals import project

    wardrobe = actors()
    wardrobe["LINA"]["visual_profile"]["worn"] = [{"item_id": "COAT"}, {"item_id": "UNDERWEAR"}]
    wardrobe["LINA"]["resolved_inventory"] = [
        {
            "id": "COAT",
            "name": "Blue coat",
            "clothing": {"layer": 2, "coverage": ["torso", "pelvis"], "opaque": True},
        },
        {
            "id": "UNDERWEAR",
            "name": "Private underwear",
            "clothing": {"layer": 0, "coverage": ["pelvis"], "underwear": True, "opaque": True},
        },
    ]
    for target, region, expected in [("UNDERWEAR", "pelvis", False), ("COAT", "torso", True)]:
        current = SimpleNamespace(
            entity_states=saved_conditions(condition(target_id=target, visual_region=region))
        )
        result = project(current, wardrobe, detailed=True)
        assert bool(result) is expected
        if expected:
            assert result[0]["actor_id"] == "LINA" and result[0]["target_name"] == "Blue coat"


def test_multiple_actor_tag_output_declares_binding_limit_for_traces_and_actions():
    from backend.engine.scene_illustrations.prompt_compiler import compile_plan
    from tests.test_prompt_compiler import english_plan_for

    facts = {
        "characters": [{"id": "LINA", "name": "Lina"}, {"id": "MIKI", "name": "Miki"}],
        "physical_conditions": [
            {"target_id": "LINA", "actor_id": "LINA", "detail": "A white bandage"}
        ],
        "visible_actions": [{"actor_ids": ["LINA"], "detail": "Lina points at the door"}],
    }
    atoms = inventory(facts)
    compiled = compile_plan(atoms, english_plan_for(atoms), "tags")
    limited = {
        row["atom_id"] for row in compiled["limitations"] if row["reason"] == "global_tag_binding"
    }
    assert {
        atom.id for atom in atoms if atom.predicate in {"physical_condition", "visible_action"}
    } <= limited
