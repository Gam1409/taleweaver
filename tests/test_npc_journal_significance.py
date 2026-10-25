"""Save lasting facts, not every gesture; keep provenance and historical changes."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.engine.npc_journal import extract as extraction_module
from backend.engine.npc_journal import worker
from backend.engine.npc_journal.extract import _known_facts
from backend.engine.npc_journal.records import append_observations, journal_of
from backend.engine.npc_journal.schema import CharacterObservation, JournalExtraction, Observation
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_npc_journal import (
    apply,
    introduction,
    journal_world,
    npc_by_id,
    portrait_world,
    save_message,
)

__all__ = ["journal_world", "portrait_world"]


def promise(**changes):
    return Observation(
        **(
            {
                "category": "event",
                "topic": "promise_return_book",
                "source": "claimed",
                "text": "Lina promised to return the book tomorrow.",
                "evidence": "I promise to return your book tomorrow.",
                "significance": "commitment",
                "effect": "new_fact",
                "reason": "An explicit future commitment the player can remember.",
            }
            | changes
        )
    )


def record(npc, observations, number=1):
    message = SimpleNamespace(
        id=f"message-{number}",
        scene_id="HALL",
        created_at=datetime(2026, 1, 1) + timedelta(days=number),
        content=" ".join(observation.evidence for observation in observations),
    )
    append_observations(npc, CharacterObservation(name="Lina", observations=observations), message)


def test_fleeting_glance_is_rejected_but_lasting_promise_is_saved():
    npc = SimpleNamespace(metadata_json={})
    glance = promise(
        text="Lina glances at the door.",
        evidence="Lina glances at the door.",
        significance="ephemeral",
        effect="none",
        reason="No lasting change.",
    )
    record(npc, [glance, promise()])
    entries = journal_of(npc)["entries"]
    assert len(entries) == 1 and entries[0]["significance"] == "commitment"
    assert entries[0]["source"] == "claimed"


@pytest.mark.parametrize(
    "changes",
    [
        {"significance": "ephemeral"},
        {"effect": "none"},
        {"effect": None},
        {"reason": None},
    ],
)
def test_new_retention_contract_needs_durable_significance_and_effect(changes):
    npc = SimpleNamespace(metadata_json={})
    record(npc, [promise(**changes)])
    assert journal_of(npc)["entries"] == []


def test_repeated_fact_across_messages_keeps_original_evidence_and_does_not_grow():
    npc = SimpleNamespace(metadata_json={})
    record(npc, [promise()])
    before = journal_of(npc)["entries"]
    for number in range(2, 20):
        record(
            npc,
            [
                promise(
                    text="  LINA promised to return the book tomorrow.  ",
                    evidence="Again: I promise to return your book tomorrow.",
                )
            ],
            number,
        )
    assert journal_of(npc)["entries"] == before


def test_changed_facts_reversals_and_claimed_versus_observed_are_preserved():
    npc = SimpleNamespace(metadata_json={})
    record(npc, [promise()])
    record(
        npc,
        [
            promise(
                text="Lina revoked the promise.",
                evidence="I cannot return it.",
                effect="changed_fact",
            )
        ],
        2,
    )
    record(npc, [promise(effect="changed_fact")], 3)
    record(npc, [promise(source="observed", effect="confirmed_claim")], 4)
    entries = journal_of(npc)["entries"]
    assert len(entries) == 4
    assert [entry["message_id"] for entry in entries] == [f"message-{i}" for i in range(1, 5)]
    assert [entry["source"] for entry in entries] == ["claimed", "claimed", "claimed", "observed"]


def test_legacy_observations_remain_valid_and_existing_entries_are_untouched():
    npc = SimpleNamespace(
        metadata_json={
            "npc_journal": {
                "entries": [
                    {
                        "id": "imported-id",
                        "message_id": "old",
                        "category": "event",
                        "topic": "general",
                        "text": "Old record",
                        "evidence": "Old record",
                        "source": "observed",
                    }
                ]
            }
        }
    )
    old = journal_of(npc)["entries"][0]
    legacy = Observation(
        category="background", text="A blacksmith", evidence="I am a blacksmith", source="claimed"
    )
    record(npc, [legacy])
    entries = journal_of(npc)["entries"]
    assert old in entries and len(entries) == 2
    assert "significance" not in entries[-1]


def test_legacy_id_replay_after_later_change_cannot_duplicate_original_fact():
    npc = SimpleNamespace(metadata_json={})
    record(npc, [promise()])
    npc.metadata_json["npc_journal"]["entries"][0]["id"] = "legacy-id"
    record(npc, [promise(text="The promise was revoked.", effect="changed_fact")], 2)
    record(npc, [promise()], 1)
    assert len(journal_of(npc)["entries"]) == 2


@pytest.mark.parametrize(
    "text",
    [
        "Я обещаю вернуть книгу завтра.",
        "明日、本を返すと約束します。",
        "Prometo devolver el libro mañana.",
    ],
)
def test_semantic_tags_support_every_story_language_without_verb_matching(text):
    npc = SimpleNamespace(metadata_json={})
    record(npc, [promise(text=text, evidence=text, reason=text, topic="general")])
    entry = journal_of(npc)["entries"][0]
    assert entry["text"] == text and entry["topic"] == "commitment"
    with pytest.raises(ValidationError):
        promise(significance=text)


def test_extraction_context_keeps_distinct_legacy_general_facts():
    npc = SimpleNamespace(metadata_json={})
    record(npc, [promise(topic="general", significance=None, effect=None, reason=None)])
    record(
        npc,
        [
            promise(
                topic="general",
                significance=None,
                effect=None,
                reason=None,
                text="She is a blacksmith.",
            )
        ],
        2,
    )
    facts = _known_facts(npc)
    assert len(facts) == 2 and "promised" in facts[0]["text"]


@pytest.mark.asyncio
async def test_live_extraction_rejects_missing_labels_but_preserves_valid_fact_and_identity(
    monkeypatch,
):
    legacy = Observation(
        category="event",
        text="Glances at a door",
        evidence="She glances at a door",
        source="observed",
    )
    incomplete = promise(effect=None)
    ephemeral = promise(significance="ephemeral", effect="none")
    result = JournalExtraction(
        characters=[
            CharacterObservation(
                name="Lina",
                self_introduction="My name is Lina",
                observations=[legacy, incomplete, ephemeral],
            ),
            CharacterObservation(name="Mira", observations=[promise()]),
        ]
    )
    llm = SimpleNamespace(model="small", aexecute_complex_task=AsyncMock(return_value=result))
    monkeypatch.setattr(extraction_module.GameMasterLLM, "for_role", lambda *args: llm)
    user = SimpleNamespace(default_language="English")
    session = SimpleNamespace(content_language="English", template_id="template", id="session")

    extracted = await extraction_module.extract(user, session, "message", "narration data")

    assert extracted.characters[0].self_introduction == "My name is Lina"
    assert extracted.characters[0].observations == []
    assert extracted.characters[1].observations == [promise()]
    llm.aexecute_complex_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_identity_survives_but_ephemeral_appearance_never_sets_portrait(journal_world):
    text = "My name is Mira. Mira glances at the door."
    message_id = await save_message(text)
    glance = promise(
        category="appearance",
        text="Glances at the door",
        evidence="Mira glances at the door.",
        significance="ephemeral",
        effect="none",
    )
    ids = await apply(message_id, [introduction("Mira", "My name is Mira", observations=[glance])])
    npc = await npc_by_id(ids[0])
    assert npc.name == "Mira" and npc.description == ""
    assert journal_of(npc)["entries"] == []


@pytest.mark.asyncio
async def test_empty_extraction_is_successful_and_uses_one_existing_model_call(
    journal_world, monkeypatch
):
    owner, portraits = journal_world
    message_id = await save_message("Lina glances at the door and adjusts a sleeve.")
    extract = AsyncMock(return_value=JournalExtraction(characters=[]))
    monkeypatch.setattr(worker, "extract", extract)
    assert await worker.process_message(message_id, owner)
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        assert message.npc_journal["status"] == "done"
    extract.assert_awaited_once()
    portraits.assert_not_called()
