"""Model agenda references resolve only against the current owner's active ledger."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from backend.engine.chpm import agenda, agenda_references, json_contract
from backend.engine.chpm.agenda_references import (
    AgendaClosureReference,
    AgendaCreation,
    AgendaReference,
)
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.memory_contracts import MemoryEntry
from backend.engine.chpm.schema import AgendaClosure, AgendaEntry, AgendaIntent, Contract


class Wire(Contract):
    agenda_change: AgendaReference | None = None


def undertaking(
    identifier: str = "goal", *, actor_id: str = "npc", text: str = "Repair the bridge"
) -> AgendaEntry:
    return AgendaEntry(
        id=identifier,
        actor_id=actor_id,
        kind="commitment",
        text=text,
        source=MemoryEntry(
            source_message_id=f"source-{identifier}",
            source_hash="source-hash",
            source_role="assistant",
            scene_id="room",
            observer_id=actor_id,
            speaker_id=actor_id,
            kind="own_speech",
            quote="I will repair the bridge.",
        ),
    )


def closed_entry(identifier: str = "closed") -> AgendaEntry:
    entry = undertaking(identifier)
    entry.closure = AgendaClosure(reason="withdraw", source=entry.source.model_copy(deep=True))
    return entry


@pytest.mark.parametrize("action", ["goal", "commitment"])
def test_creation_keeps_new_authored_text_and_the_canonical_shape(action: str) -> None:
    wire: AgendaReference = TypeAdapter(AgendaReference).validate_python(
        {"action": action, "text": "Find a safe route home"}
    )

    canonical = agenda_references.materialize(wire, [], "npc")

    assert isinstance(wire, AgendaCreation)
    assert canonical is not None
    assert canonical.model_dump() == {
        "action": action,
        "text": "Find a safe route home",
        "entry_id": None,
    }
    assert AgendaIntent.model_validate(canonical.model_dump()) == canonical


@pytest.mark.parametrize("action", ["withdraw", "report_done"])
def test_closure_carries_only_an_id_and_host_derives_canonical_text(action: str) -> None:
    entries = [undertaking()]
    wire: AgendaReference = TypeAdapter(AgendaReference).validate_python(
        {"action": action, "entry_id": "goal"}
    )
    before = deepcopy((entries, wire))

    canonical = agenda_references.materialize(wire, entries, "npc")

    assert isinstance(wire, AgendaClosureReference)
    assert wire.model_dump() == {"action": action, "entry_id": "goal"}
    assert canonical is not None
    assert canonical.model_dump() == {
        "action": action,
        "entry_id": "goal",
        "text": "Repair the bridge",
    }
    assert (entries, wire) == before
    agenda.validate_intent(canonical, entries)


@pytest.mark.parametrize(
    "body",
    [
        {"action": "withdraw"},
        {"action": "report_done", "entry_id": None},
        {"action": "withdraw", "entry_id": "goal", "text": "Repair the bridge"},
        {"action": "report_done", "entry_id": "goal", "text": "Different text"},
        {"action": "goal", "text": "New business", "entry_id": "goal"},
        {"action": "commitment", "text": "New business", "entry_id": None},
        {"action": "goal"},
        {"action": "goal", "text": " "},
        {"action": "commitment", "text": "x" * 301},
        {"action": "withdraw", "entry_id": "x" * 65},
    ],
)
def test_wire_rejects_repeated_closure_text_and_invalid_shapes(body: dict) -> None:
    with pytest.raises(ValidationError):
        Wire.model_validate({"agenda_change": body})


@pytest.mark.parametrize("case", ["missing", "foreign", "closed", "retracted"])
def test_unavailable_reference_fails_without_mutating_current_entries(case: str) -> None:
    scopes = {
        "missing": [],
        "foreign": [undertaking(actor_id="other")],
        "closed": [closed_entry("goal")],
        "retracted": agenda.retract([undertaking()], "source-goal"),
    }
    entries = scopes[case]
    before = deepcopy(entries)
    wire = AgendaClosureReference(action="withdraw", entry_id="goal")

    with pytest.raises(ChpmError, match="active owned"):
        agenda_references.materialize(wire, entries, "npc")

    assert entries == before


@pytest.mark.parametrize("entry_id", [" goal", "goal ", "\tgoal\n", " "])
def test_raw_closure_ids_are_never_trimmed_into_an_owned_reference(entry_id: str) -> None:
    wire = AgendaClosureReference(action="withdraw", entry_id=entry_id)
    identifiers = {"entry_id": agenda_references.active_ids([undertaking()], "npc")}
    validator = Draft202012Validator(json_contract.response_schema(Wire, identifiers))

    assert wire.entry_id == entry_id
    assert not validator.is_valid({"agenda_change": wire.model_dump()})
    with pytest.raises(ChpmError, match="active owned"):
        agenda_references.materialize(wire, [undertaking()], "npc")


def test_same_text_is_never_used_to_find_another_owned_or_foreign_id() -> None:
    entries = [
        undertaking("first"),
        undertaking("second"),
        undertaking("foreign", actor_id="other"),
    ]

    canonical = agenda_references.materialize(
        AgendaClosureReference(action="withdraw", entry_id="second"), entries, "npc"
    )

    assert canonical is not None and canonical.entry_id == "second"
    with pytest.raises(ChpmError, match="active owned"):
        agenda_references.materialize(
            AgendaClosureReference(action="withdraw", entry_id="foreign"), entries, "npc"
        )


def test_active_ids_are_owned_and_open_and_bind_the_actual_decoder_schema() -> None:
    entries = [undertaking(), undertaking("foreign", actor_id="other"), closed_entry()]
    identifiers = {"entry_id": agenda_references.active_ids(entries, "npc")}
    schema = json_contract.response_schema(Wire, identifiers, explicit_keys=True)
    validator = Draft202012Validator(schema)

    assert identifiers == {"entry_id": ["goal"]}
    assert validator.is_valid({"agenda_change": {"action": "withdraw", "entry_id": "goal"}})
    assert validator.is_valid({"agenda_change": {"action": "commitment", "text": "New business"}})
    assert not validator.is_valid({"agenda_change": {"action": "withdraw", "entry_id": "foreign"}})
    assert not validator.is_valid({"agenda_change": {"action": "withdraw", "entry_id": "closed"}})
    assert not validator.is_valid(
        {"agenda_change": {"action": "withdraw", "entry_id": "goal", "text": "Repair the bridge"}}
    )


def test_no_active_ids_prunes_closure_choices_without_disabling_creation_or_null() -> None:
    schema = json_contract.response_schema(Wire, {"entry_id": []}, explicit_keys=True)
    validator = Draft202012Validator(schema)

    assert validator.is_valid({"agenda_change": None})
    assert validator.is_valid({"agenda_change": {"action": "goal", "text": "New business"}})
    assert not validator.is_valid({"agenda_change": {"action": "withdraw", "entry_id": "invented"}})
    assert "AgendaClosureReference" not in schema.get("$defs", {})


def test_full_active_cap_rejects_creation_and_preserves_closure_availability() -> None:
    entries = [
        undertaking(str(index), text=f"Business {index}") for index in range(agenda.MAX_ACTIVE)
    ]
    identifiers = {"entry_id": agenda_references.active_ids(entries, "npc")}
    validator = Draft202012Validator(json_contract.response_schema(Wire, identifiers))
    closure = AgendaClosureReference(action="report_done", entry_id="0")

    assert validator.is_valid({"agenda_change": closure.model_dump()})
    assert agenda_references.materialize(closure, entries, "npc") is not None
    with pytest.raises(ChpmError, match="active agenda is full"):
        agenda_references.materialize(
            AgendaCreation(action="goal", text="New business"), entries, "npc"
        )


def test_creation_still_rejects_existing_duplicate_and_ignores_foreign_active_cap() -> None:
    foreign = [
        undertaking(str(index), actor_id="other", text=f"Business {index}")
        for index in range(agenda.MAX_ACTIVE)
    ]
    wire = AgendaCreation(action="goal", text="Repair the bridge")

    assert agenda_references.materialize(wire, foreign, "npc") is not None
    with pytest.raises(ChpmError, match="duplicates"):
        agenda_references.materialize(wire, [undertaking()], "npc")


@pytest.mark.parametrize("case", ["duplicate", "overfull"])
def test_ambiguous_or_overfull_active_scope_is_rejected(case: str) -> None:
    invalid = {
        "duplicate": [undertaking(), undertaking()],
        "overfull": [undertaking(str(index)) for index in range(agenda.MAX_ACTIVE + 1)],
    }

    with pytest.raises(ChpmError):
        agenda_references.active_ids(invalid[case], "npc")
    with pytest.raises(ChpmError):
        agenda_references.materialize(
            AgendaClosureReference(action="withdraw", entry_id=invalid[case][0].id),
            invalid[case],
            "npc",
        )


def test_materialization_rechecks_models_modified_after_initial_validation() -> None:
    invalid = AgendaClosureReference(action="withdraw", entry_id="goal").model_copy(
        update={"text": "Different text"}
    )

    with pytest.raises(ValidationError):
        agenda_references.materialize(invalid, [undertaking()], "npc")


def test_explicit_legacy_wrong_text_is_still_rejected_by_the_canonical_owner() -> None:
    wrong = AgendaIntent(action="withdraw", entry_id="goal", text="Different text")

    with pytest.raises(ChpmError, match="exactly"):
        agenda.validate_intent(wrong, [undertaking()])


def test_null_remains_no_change() -> None:
    assert agenda_references.materialize(None, [undertaking()], "npc") is None
