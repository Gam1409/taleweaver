"""Admitted causes keep their source age through decision, narration and repair."""

import json

import pytest

from backend.engine.chpm import (
    cognitive_context,
    experience,
    motivation,
    narration_repair_input,
    prompts,
    rendering,
    runtime,
)
from backend.engine.chpm.appraisal_contracts import INSTRUCTIONS
from backend.engine.chpm.host_state import Mind, before_messages
from backend.engine.chpm.schema import Settings
from tests.test_chpm_compact_contract import contract_fixture
from tests.test_chpm_experience_packing import with_reasons
from tests.test_chpm_kernel import observation


@pytest.mark.parametrize("gap", [False, True])
@pytest.mark.parametrize("restored", [False, True])
def test_backfilled_causes_survive_current_handoffs_without_refresh_or_mutation(gap, restored):
    value = with_reasons(('"' * 180, "\\" * 180, "The unmet need remains relevant."))
    if restored:
        value = Mind.model_validate_json(value.model_dump_json())
    before = value.model_dump_json()
    turn, _ = contract_fixture()
    turn.minds["npc"] = value
    if gap:
        turn.gap_cursors = {"npc": value.snapshot.cursor}
    current = observation().model_copy(
        update={"message_id": "packing-2", "player_request": "The inspector reported update 2."}
    )
    supplied = {"observation": current.model_dump(), "_chpm_gap_cursors": turn.gap_cursors}
    instruction = prompts.PROPOSE + INSTRUCTIONS + motivation.INSTRUCTIONS + experience.INSTRUCTIONS

    _, _, payload, _ = cognitive_context.pack(value, current, supplied, [], Settings(), instruction)
    narrated = runtime.contract_data(turn)
    reviewed = rendering._review_payload(turn, {}, "No completed repair")["contract"]
    _, repaired = narration_repair_input.build(
        turn, "Original policy", "Rejected wording", "No completed repair", [], portrait_reminder=""
    )

    projected = narrated["npc"]["subjective_experience_not_traits"]
    assert projected == payload["experience_context"]
    assert narrated == reviewed == json.loads(repaired)["dialogue_contract"]
    states = {row["dimension"]: row for row in projected["states"]}
    assert states["autonomy"]["last_assessed_reason"] == "The unmet need remains relevant."
    assert states["anger"]["last_assessed_level"] == "moderate"
    assert all(
        row["status"] == ("historical_current_unknown" if gap else "recent_appraisal")
        for row in states.values()
    )
    original = {row.record_id: row.sim_minute for row in value.snapshot.experiences}
    assert all(row["assessed_at_minute"] == original[row["record_id"]] for row in states.values())
    assert value.model_dump_json() == before
    assert turn.usage.calls == 0


def test_retracting_a_source_removes_its_reason_instead_of_recovering_it_from_projection():
    value = with_reasons(('"' * 180, "\\" * 180, "A source-bound concern."))
    prior = before_messages(value, {"packing-2"})
    projected = runtime.contract_data(contract_with_mind(prior))
    serialized = json.dumps(projected)
    assert "A source-bound concern." not in serialized
    assert {row.dimension for row in prior.snapshot.experiences} == {"fear", "anger"}
    assert len(value.snapshot.experiences) == 3


def contract_with_mind(value: Mind) -> runtime.Turn:
    turn, _ = contract_fixture()
    turn.minds["npc"] = value
    return turn
