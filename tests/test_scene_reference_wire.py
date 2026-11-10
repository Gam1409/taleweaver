"""The request advertises exact finite references; saved contracts remain unchanged."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from backend.engine.narrated_items.evidence import Catalog, bind, bind_staging
from backend.engine.narrated_items.reference_schema import build
from backend.engine.narrated_items.schema import ItemExtraction, SharedItemExtraction
from backend.engine.scene_staging.proposals import StagingProposal, validate
from tests.test_scene_source_references import NARRATION, ROOM, proposal


def test_wire_schema_only_advertises_this_request_references_and_no_source_labels():
    catalog = Catalog(NARRATION, ROOM, scope="turn-1")
    before = deepcopy(SharedItemExtraction.model_json_schema())
    wire = build(SharedItemExtraction, catalog)
    assert SharedItemExtraction.model_json_schema() == before
    assert "source" not in wire["$defs"]["Update"]["properties"]
    validator = Draft202012Validator(wire)
    reference = next(iter(catalog.narration_passages))
    assert validator.is_valid({"scene_updates": [proposal(reference)]})
    assert not validator.is_valid({"scene_updates": [proposal("The kettle starts heating.")]})
    assert not validator.is_valid({"scene_updates": [proposal(reference, source="narration")]})
    other = Catalog(NARRATION, ROOM, scope="turn-2")
    assert not validator.is_valid(
        {"scene_updates": [proposal(next(iter(other.narration_passages)))]}
    )
    assert validator.is_valid(
        {"scene_updates": [proposal(next(iter(catalog.room_passages)), kind="environment")]}
    )


def test_bad_reference_only_unconfirms_its_actor_and_leaves_valid_pose():
    catalog = Catalog("Lina sits on the bench. Miki stands by the desk.", ROOM, scope="test")
    good = list(catalog.narration_passages)[1]
    result = bind_staging(
        StagingProposal(
            changes=[
                {
                    "entity_id": "LINA",
                    "posture": "sitting",
                    "evidence": next(iter(catalog.room_passages)),
                },
                {"entity_id": "MIKI", "posture": "standing", "evidence": good},
            ]
        ),
        catalog,
    )
    checked = validate(result)
    assert checked.unconfirmed_actors == {"LINA"}
    assert [row.entity_id for row in checked.value.changes] == ["MIKI"]
    assert checked.value.changes[0].evidence_span.start > 0


def test_binding_covers_frame_actions_and_item_placements_without_mutating_proposal():
    catalog = Catalog("Lina sits on the bench. Lina puts a scarf on the table.", ROOM, scope="test")
    refs = list(catalog.narration_passages)
    result = SharedItemExtraction(
        final_frame_actions=[
            {"actor_ids": ["LINA"], "detail": "Lina is sitting.", "evidence": refs[0]}
        ],
        staging={
            "changes": [{"entity_id": "LINA", "posture": "sitting", "evidence": refs[0]}],
            "props": [{"item_id": "SCARF", "owner_id": "LINA", "evidence": refs[1]}],
        },
    )
    before = result.model_dump()
    selected = bind(result, catalog.narration, catalog=catalog)
    assert result.model_dump() == before
    assert selected.final_frame_actions[0]["evidence"] == "Lina sits on the bench."
    assert selected.staging["props"][0]["evidence_span"]["start"] > 0


@pytest.mark.parametrize("model", [ItemExtraction, SharedItemExtraction, StagingProposal])
@pytest.mark.parametrize("text,room", [("", ""), ("OK", ""), ("", ROOM)])
def test_missing_source_choices_disable_only_unavailable_operations(model, text, room):
    from backend.core.llm_schema_projection import project

    catalog = Catalog(text, room, scope="empty-source")
    wire = build(model, catalog)
    Draft202012Validator.check_schema(wire)
    projected = project(wire).schema
    Draft202012Validator.check_schema(projected)
    assert Draft202012Validator(projected).is_valid({})
    if model is not StagingProposal:
        validator = Draft202012Validator(wire)
        candidate = proposal("invented-reference")
        assert not validator.is_valid({"scene_updates": [candidate]})
        if room:
            candidate = proposal(next(iter(catalog.room_passages)), kind="environment")
            assert validator.is_valid({"scene_updates": [candidate]})


@pytest.mark.parametrize("mode", ["json_schema", "json_object", "prompt"])
@pytest.mark.parametrize("synchronous", [False, True])
async def test_router_uses_request_schema_in_provider_policy_and_prompt(
    monkeypatch, mode, synchronous
):
    from tests.test_custom_openai import make_router

    catalog = Catalog(NARRATION, ROOM, scope="test")
    wire = build(ItemExtraction, catalog)
    router = make_router()
    router.model = "vendor/model"
    router.custom_response_format = mode
    captured = {}

    def respond(kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"actions":[]}'), finish_reason="stop"
                )
            ],
            model_dump=lambda: {},
        )

    if synchronous:
        monkeypatch.setattr(router, "_completion_with_openrouter_fallback", respond)
        answer = router.execute_complex_task(
            "Extract.", "Text.", ItemExtraction, router.model, response_schema=wire
        )
    else:

        async def invoke(kwargs):
            return respond(kwargs)

        monkeypatch.setattr(router, "_acompletion_with_openrouter_fallback", invoke)
        answer = await router.aexecute_complex_task(
            "Extract.", "Text.", ItemExtraction, router.model, response_schema=wire
        )
    assert not answer.actions
    if mode == "json_schema":
        defs = captured["response_format"]["json_schema"]["schema"]["$defs"]
        assert defs["NarrationEvidenceReference"]["enum"] == catalog.references()
        assert "source" not in str(defs["Update"].get("properties", {}))
    else:
        prompt = captured["messages"][0]["content"]
        assert next(iter(catalog.narration_passages)) in prompt
        assert "scene_description" not in prompt
