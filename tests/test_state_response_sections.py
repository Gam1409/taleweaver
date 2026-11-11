"""Missing response sections are unknown, distinct from explicit unchanged arrays."""

import json
from types import SimpleNamespace

import pytest

from backend.core.llm_router import GameMasterLLM
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.runtime import KEY, reconcile_items
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import read as conditions
from backend.engine.scene_continuity.ledger import read as scene
from backend.engine.scene_staging import props, shared
from backend.engine.scene_staging.state import KEY as STAGING_KEY
from tests.conftest import TestSessionLocal
from tests.test_shared_scene_staging import SharedRoles, seed
from tests.test_vn_turn_integration import final_payload

TEXT = "Lina has ink on her hand. A lamp stays lit beside the door."
FIELDS = ("actions", "condition_updates", "scene_updates", "final_frame_actions")


class SectionRoles(SharedRoles):
    omit = None

    async def structured(self, *args, **kwargs):
        model = kwargs.get("response_model") or args[2]
        if not issubclass(model, ItemExtraction):
            return await super().structured(*args, **kwargs)
        self.calls.append((model.__name__, args, kwargs))
        body = {key: [] for key in FIELDS}
        body["condition_updates"] = [
            {
                "operation": "record",
                "target_id": "LINA",
                "kind": "contamination",
                "part": "hand",
                "detail": "Ink on the hand",
                "evidence": "Lina has ink on her hand.",
            }
        ]
        body["scene_updates"] = [
            {
                "operation": "record",
                "key": "lamp",
                "kind": "process",
                "subject_id": "START",
                "detail": "A lamp stays lit",
                "evidence": "A lamp stays lit beside the door.",
            }
        ]
        if self.omit:
            body.pop(self.omit)
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(body)),
                    finish_reason="stop",
                )
            ]
        )
        return GameMasterLLM._parse_structured_content(
            object.__new__(GameMasterLLM), response, model
        )


@pytest.mark.parametrize("omitted", [None, *FIELDS])
async def test_partial_response_does_not_masquerade_as_a_complete_unchanged_check(
    monkeypatch, omitted
):
    async with TestSessionLocal() as db:
        roles = SectionRoles()
        roles.omit = omitted
        _, user, _, state = await seed(monkeypatch, db, enabled=False, roles=roles)
        monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", TEXT)
        events = [
            chunk
            async for chunk in GameTurnManager(db, state.session_id, user).process_turn("Continue.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        check = state.entity_states[KEY]
        assert check["status"] == ("needs_review" if omitted else "complete")
        assert check.get("unconfirmed_sections", []) == ([omitted] if omitted else [])
        assert bool(conditions(state.entity_states).conditions) is (omitted != "condition_updates")
        assert bool(scene(state.entity_states).records) is (omitted != "scene_updates")
        assert len(roles.calls) == 3
        assert check["message_id"] in check["processed_message_ids"]
        schema = roles.calls[-1][2]["response_schema"]
        assert set(schema["required"]) == set(FIELDS)
        assert "staging" not in schema["properties"]


def test_complete_wire_contract_requires_explicit_sections_without_changing_local_models():
    from jsonschema import Draft202012Validator

    from backend.engine.narrated_items.evidence import Catalog
    from backend.engine.narrated_items.reference_schema import build
    from backend.engine.narrated_items.response_sections import read
    from backend.engine.narrated_items.schema import SharedItemExtraction

    catalog = Catalog(TEXT, "", scope="test")
    before = ItemExtraction.model_json_schema()
    packet = {key: [] for key in FIELDS}
    wire = build(ItemExtraction, catalog, complete=True)
    validator = Draft202012Validator(wire)
    assert validator.is_valid(packet)
    assert not validator.is_valid({})
    assert not validator.is_valid({"actions": []})
    assert ItemExtraction.model_json_schema() == before
    assert read(ItemExtraction(actions=[]), staging=False).unconfirmed
    wire = build(SharedItemExtraction, catalog, complete=True)
    validator = Draft202012Validator(wire)
    assert validator.is_valid({**packet, "staging": {"changes": [], "props": [], "explicit": []}})
    assert not validator.is_valid({**packet, "staging": {"changes": [], "props": []}})


@pytest.mark.parametrize("missing", ["changes", "props", "explicit"])
async def test_missing_staging_subsection_keeps_independent_confirmed_sections(
    monkeypatch, missing
):
    class PartialStaging(SharedRoles):
        async def structured(self, *args, **kwargs):
            result = await super().structured(*args, **kwargs)
            if isinstance(result, ItemExtraction):
                result.staging.pop(missing)
            return result

    async with TestSessionLocal() as db:
        roles, user, _, state = await seed(monkeypatch, db, roles=PartialStaging())
        manager = GameTurnManager(db, state.session_id, user)
        events = [chunk async for chunk in manager.process_turn("Continue.")]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        ledger = state.entity_states[KEY]
        staging = state.entity_states[STAGING_KEY]
        assert ledger["unconfirmed_sections"] == [f"staging.{missing}"]
        assert staging["unconfirmed_sections"] == [missing]
        lina = state.entity_states["LINA"]
        assert not lina["visual_profile"]["worn"]
        if missing == "changes":
            assert "LINA" in staging["unconfirmed_actors"]
        else:
            assert staging["actors"]["LINA"]["posture"]["value"] == "sitting"
        if missing != "props":
            assert state.entity_states[props.KEY]["items"][0]["spatial_position"] == "on the bench"
        else:
            assert not state.entity_states.get(props.KEY, {}).get("items")
        assert len(roles.calls) == 3
        from copy import deepcopy

        before = deepcopy(state.entity_states)
        from tests.test_shared_scene_staging import TEXT as SOURCE

        assert await reconcile_items(manager, SOURCE, completed=True, resolution="") == []
        assert shared.consume(manager, SOURCE, completed=True)
        assert state.entity_states == before
        assert len(roles.calls) == 3


@pytest.mark.parametrize("mode", ["json_schema", "json_object", "prompt"])
@pytest.mark.parametrize("omit", [False, True])
async def test_router_modes_keep_independent_data_and_original_section_presence(
    monkeypatch, mode, omit
):
    from backend.engine.narrated_items.evidence import Catalog
    from backend.engine.narrated_items.reference_schema import build
    from backend.engine.narrated_items.response_sections import read
    from backend.engine.narrated_items.schema import SharedItemExtraction
    from tests.test_custom_openai import make_router

    router = make_router()
    router.model, router.custom_response_format = "vendor/model", mode
    wire = build(ItemExtraction, Catalog(TEXT, scope="wire"), complete=True)
    packet = {key: [] for key in FIELDS}
    packet["actions"] = [{"item_id": "COAT", "source_owner": "LINA"}]
    packet["scene_updates"] = [
        {
            "operation": "record",
            "key": "lamp",
            "subject_id": "START",
            "detail": "A lamp stays lit",
            "evidence": "A lamp stays lit beside the door.",
        }
    ]
    if omit:
        packet.pop("condition_updates")
    requests = []

    async def respond(kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(packet)), finish_reason="stop"
                )
            ],
            model_dump=lambda: {},
        )

    monkeypatch.setattr(router, "_acompletion_with_openrouter_fallback", respond)
    result = await router.aexecute_complex_task(
        "Extract state.", TEXT, SharedItemExtraction, router.model, response_schema=wire
    )
    assert len(requests) == 1
    assert len(result.scene_updates) == len(result.actions) == 1
    assert read(result, staging=False).unconfirmed == (("condition_updates",) if omit else ())
    if mode == "json_schema":
        advertised = requests[0]["response_format"]["json_schema"]["schema"]
        assert "staging" not in advertised["properties"]
        assert set(advertised["required"]) == set(FIELDS)
