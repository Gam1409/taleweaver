"""Full proposal requests retain evidence and reserve space before any dispatch."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import cognitive_proposal, development_context, inference
from backend.engine.chpm.cognitive_context import ContextBudgetError
from backend.engine.chpm.schema import Settings
from tests.test_chpm_appraisal import heard
from tests.test_chpm_development import history
from tests.test_chpm_kernel import observation


def prepare(value, settings):
    return cognitive_proposal.prepare(
        SimpleNamespace(game_id="session"),
        settings,
        "npc",
        observation(),
        {},
        [],
        value,
        None,
        pinned={},
        pinned_beliefs={},
        focus=(),
        hits=[],
        audit=[],
        notebook=None,
    )


@pytest.mark.parametrize("eligible", [False, True])
def test_only_available_development_includes_its_operation_guidance(eligible):
    value = history() if eligible else history((1, 2, 3))
    before = value.model_dump_json()
    prepared = prepare(value, Settings(mode="live", actor_ids=["npc"], max_input_chars=64000))
    context = prepared.payload["development_context"]
    expected = development_context.payload(
        value, development_context.episodes(value) if eligible else {}
    )
    assert context["current_tendencies"] == expected["current_tendencies"]
    assert context["basis"] == expected["basis"]
    assert context["status"] == ("available" if eligible else "not_yet_eligible")
    guidance = {"scope", "minimum_span_minutes", "sampling"}
    assert guidance & context.keys() == (guidance if eligible else set())
    assert ("developments" in prepared.schema.model_fields) is eligible
    assert value.model_dump_json() == before


@pytest.mark.parametrize("overflow", [0, 1, None], ids=["exact", "one_over", "small_budget"])
def test_actual_wire_boundary_preserves_the_existing_repair_reserve_and_exact_sources(overflow):
    value = heard(message="input", text="The inspection is complete. Two  spaces remain exact.")
    before = value.model_dump_json()
    settings = Settings(mode="live", actor_ids=["npc"])
    prepared = prepare(value, settings)
    original = deepcopy(prepared.payload)
    system, content = inference.compose(
        prepared.instruction, prepared.payload, prepared.schema, prepared.identifiers
    )
    size = len(system) + len(content)
    limit = 8000 if overflow is None else size + 2048 - overflow
    bounded = settings.model_copy(update={"max_input_chars": limit})
    if overflow != 0:
        with pytest.raises(ContextBudgetError, match=rf"{size} > {limit - 2048} characters"):
            prepare(value, bounded)
    else:
        result = prepare(value, bounded)
        wire = inference.compose(
            result.instruction, result.payload, result.schema, result.identifiers
        )
        assert sum(map(len, wire)) + 2048 == limit
        assert result.payload["context_packing"]["tier"] == 0
        assert result.references.quotes == prepared.references.quotes
        assert result.references.observer_id == prepared.references.observer_id == "npc"
        assert result.payload["appraisal_context"] == prepared.payload["appraisal_context"]
    assert settings.max_input_chars == 24000 and bounded.max_input_chars == limit
    assert value.model_dump_json() == before and prepared.payload == original
