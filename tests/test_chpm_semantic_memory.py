"""Observer semantic recall preserves original evidence, episode identity and handoff limits."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.chpm import agent_context, semantic_recall, semantic_sources
from backend.engine.chpm.host_state import Source, record
from backend.engine.chpm.kernel import ChpmError, digest
from backend.engine.chpm.schema import Settings, Usage
from backend.engine.memory_rag.store import Scope
from tests.test_chpm_compact_contract import contract_fixture
from tests.test_chpm_host_state import mind
from tests.test_chpm_kernel import observation
from tests.test_chpm_memory import source


def remembered(actor="npc", scene="CLINIC"):
    row = source("old", "The collected sample is in the blue vial.", scene_id=scene)
    value = record(
        mind(actor),
        Source(
            message_id=row.id,
            revision_id=row.revision_id,
            content_hash=digest(row.content),
            role=row.role,
            speaker_id=actor,
            kind="narration",
            text=row.content,
        ),
        minute=0,
    )
    rows = {row.id: row}
    scope = Scope("owner", "session", 3, "observer-signature", namespace="observer")
    item = semantic_sources.episodes(value, "owner", "template", rows)[0]
    candidate = item.document.to_dict() | {"epoch": scope.epoch, "signature": scope.signature}
    return value, rows, scope, candidate


@pytest.mark.parametrize(
    "field,changed",
    [
        ("user_id", "foreign"),
        ("session_id", "foreign"),
        ("npc_id", "other"),
        ("epoch", 2),
        ("signature", "wrong"),
        ("source_hash", "edited"),
        ("layer", "dialogue"),
        ("source_id", "wrong"),
        ("template_id", "other"),
    ],
)
def test_foreign_or_stale_vector_rows_never_become_observer_memory(field, changed):
    value, rows, scope, candidate = remembered()
    assert semantic_recall.validate(value, "owner", "template", rows, [candidate], scope)
    assert (
        semantic_recall.validate(
            value, "owner", "template", rows, [candidate | {field: changed}], scope
        )
        == []
    )


def test_vector_text_is_not_trusted_and_edited_messages_are_rejected():
    value, rows, scope, candidate = remembered()
    hits = semantic_recall.validate(
        value, "owner", "template", rows, [candidate | {"text": "Forged memory"}], scope
    )
    assert hits[0].text == rows["old"].content
    rows["old"].content = "The old claim was corrected."
    assert semantic_recall.validate(value, "owner", "template", rows, [candidate], scope) == []


def test_wrong_root_scope_is_a_host_error_instead_of_a_public_fallback():
    value, rows, scope, candidate = remembered()
    with pytest.raises(ChpmError):
        semantic_recall.validate(
            value, "owner", "template", rows, [candidate], replace(scope, namespace="public")
        )


def test_interrupted_narration_cannot_be_indexed_as_canonical_knowledge():
    value, rows, scope, candidate = remembered()
    rows["old"].npc_journal = {"status": "incomplete"}
    assert semantic_recall.validate(value, "owner", "template", rows, [candidate], scope) == []


def test_similar_events_keep_both_places_and_their_order_through_narration_handoff():
    value, rows, scope, first = remembered()
    later = source("later", rows["old"].content, scene_id="EMBASSY")
    second_source = next(iter(value.sources.values())).model_copy(update={"message_id": later.id})
    value = record(value, second_source, minute=1)
    rows[later.id] = later
    items = semantic_sources.episodes(value, "owner", "template", rows)
    candidates = [
        item.document.to_dict() | {"epoch": scope.epoch, "signature": scope.signature}
        for item in items
    ]
    hits = semantic_recall.validate(value, "owner", "template", rows, candidates, scope)
    pins = semantic_recall.merge(value, {}, hits)
    assert len(pins) == 2
    turn, _ = contract_fixture()
    turn.decisions["npc"].agent_evidence = agent_context.collect(
        pins, observation(), contexts=semantic_recall.contexts(pins, hits)
    )
    presented = agent_context.present(turn.decisions["npc"], value)
    assert {entry["context"]["scene_id"] for entry in presented} == {"CLINIC", "EMBASSY"}
    assert [entry["context"]["evidence_order"] for entry in presented] == [0, 1]
    assert all(entry["kind"] == "reported" for entry in presented)


def test_semantic_pins_share_the_existing_count_and_character_budget():
    value, rows, scope, candidate = remembered()
    hit = semantic_recall.validate(value, "owner", "template", rows, [candidate], scope)[0]
    original = {
        f"c{i}": (f"key{i}", next(iter(value.sources.values())), "x" * 1000) for i in range(6)
    }
    assert semantic_recall.merge(value, original, [hit]) == original
    original = {f"c{i}": (f"key{i}", next(iter(value.sources.values())), "x") for i in range(8)}
    assert semantic_recall.merge(value, original, [hit]) == original


async def test_disabled_semantics_makes_no_database_or_embedding_calls(monkeypatch):
    embed = AsyncMock(side_effect=AssertionError("No semantic request expected"))
    monkeypatch.setattr(semantic_recall, "embed_texts", embed)
    turn = SimpleNamespace(initial=SimpleNamespace(settings=Settings()), usage=Usage())
    await semantic_recall.prepare(SimpleNamespace(), turn, ["npc"], observation())
    assert turn.usage.semantic_recall == {}
    embed.assert_not_awaited()


def test_legacy_kernel_settings_keep_semantic_memory_disabled():
    from backend.engine.chpm.schema import KernelState

    raw = KernelState().model_dump()
    raw["settings"].pop("semantic_memory")
    assert not KernelState.model_validate(raw).settings.semantic_memory
    assert KernelState.model_validate(raw).schema_version == 6
