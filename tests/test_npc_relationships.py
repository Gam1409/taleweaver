"""Relationship badges reflect learned evidence, survive saves and respect rewind."""

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.engine.npc_journal.lifecycle import rewind_journals
from backend.engine.npc_journal.records import journal_of
from backend.engine.npc_journal.relationships import player_relationship
from backend.engine.npc_journal.schema import CharacterObservation, Observation
from backend.models.world_entity import WorldEntity
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


def attitude(status="trust", **overrides):
    return Observation(
        **{
            "category": "relationship",
            "topic": "relationship_player",
            "text": "Говорит, что доверяет вам",
            "evidence": "Я тебе доверяю",
            "source": "claimed",
            "player_attitude": status,
            **overrides,
        }
    )


async def introduced_with_trust():
    message_id = await save_message("«Меня зовут Мира». «Я тебе доверяю».")
    npc_id = (await apply(message_id, [introduction(observations=[attitude()])]))[0]
    return message_id, npc_id


async def test_no_evidence_means_unknown_even_when_private_notes_claim_love(
    auth_client, journal_world
):
    message_id = await save_message()
    npc_id = (await apply(message_id, [introduction()]))[0]
    async with TestSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session", WorldEntity.id == npc_id
            )
        )
        npc.notes = "Secretly in love with the player."
        await db.commit()
    response = await auth_client.get(f"/api/adventures/portrait-session/npcs/{npc_id}")
    assert response.status_code == 200
    relationship = response.json()["relationship"]
    assert relationship["status"] == "unknown"
    assert relationship["source"] is None
    assert relationship["evidence"] is None


async def test_claimed_trust_is_shown_with_evidence_on_card_and_directory(
    auth_client, journal_world
):
    _, npc_id = await introduced_with_trust()
    detail = (await auth_client.get(f"/api/adventures/portrait-session/npcs/{npc_id}")).json()
    relationship = detail["relationship"]
    assert relationship["status"] == "trust"
    assert relationship["source"] == "claimed"
    assert relationship["evidence"] == "Я тебе доверяю"
    assert relationship["text"] == "Говорит, что доверяет вам"
    directory = (await auth_client.get("/api/adventures/portrait-session/npcs")).json()
    card = next(c for c in directory["characters"] if c["id"] == npc_id)
    assert card["relationship"] == relationship
    assert detail["entries"][0]["player_attitude"] == "trust"


async def test_attitude_changes_preserve_history_and_rewind_restores_previous(journal_world):
    _, npc_id = await introduced_with_trust()
    later = await save_message("Мира подозрительно следит за вашими руками.")
    await apply(
        later,
        [
            CharacterObservation(
                name="Мира",
                npc_id=npc_id,
                observations=[
                    attitude(
                        "suspicion",
                        text="Подозрительно наблюдает за вами",
                        source="observed",
                        evidence="Мира подозрительно следит за вашими руками.",
                    )
                ],
            )
        ],
    )
    journal = journal_of(await npc_by_id(npc_id))
    assert player_relationship(journal)["status"] == "suspicion"
    assert player_relationship(journal)["source"] == "observed"
    assert [e["player_attitude"] for e in journal["entries"]] == ["trust", "suspicion"]
    async with TestSessionLocal() as db:
        await rewind_journals(db, "portrait-session", [later])
        await db.commit()
    assert player_relationship(journal_of(await npc_by_id(npc_id)))["status"] == "trust"


async def test_unsupported_quote_cannot_change_attitude(journal_world):
    _, npc_id = await introduced_with_trust()
    later = await save_message("Мира закрыла дверь.")
    await apply(
        later,
        [
            CharacterObservation(
                name="Мира", npc_id=npc_id, observations=[attitude("love", evidence="Я люблю тебя")]
            )
        ],
    )
    assert player_relationship(journal_of(await npc_by_id(npc_id)))["status"] == "trust"


@pytest.mark.parametrize(
    "category,topic",
    [
        ("appearance", "relationship_player"),
        ("relationship", "relationship_sister"),
        ("relationship", "player_toward_npc"),
    ],
)
def test_other_people_and_unrelated_topics_do_not_set_player_attitude(category, topic):
    earlier = attitude().model_dump()
    unrelated = attitude("love", category=category, topic=topic).model_dump()
    assert player_relationship({"entries": [earlier, unrelated]})["status"] == "trust"


def test_old_freeform_and_unclear_assessments_are_not_guessed_from_language():
    old = attitude("love").model_dump()
    old.pop("player_attitude")
    old["text"] = "Любовь / Love / 愛"
    assert player_relationship({"entries": [old]})["status"] == "unknown"
    assert player_relationship({"entries": [attitude().model_dump(), old]})["status"] == "unknown"
    assert (
        player_relationship({"entries": [attitude("neutral").model_dump()]})["status"] == "neutral"
    )


def test_invalid_numeric_or_invented_relationship_scores_are_rejected():
    for value in (95, "love:100", "secretly_in_love"):
        with pytest.raises(ValidationError):
            attitude(value)


async def test_copy_and_export_import_keep_attitude_and_latest_summary_on_any_page(
    auth_client, journal_world
):
    _, npc_id = await introduced_with_trust()
    path = f"/api/adventures/portrait-session/npcs/{npc_id}"
    expected = (await auth_client.get(path)).json()["relationship"]
    page = (await auth_client.get(path + "?offset=50")).json()
    assert page["entries"] == [] and page["relationship"] == expected
    copied = await auth_client.post("/api/adventures/sessions/portrait-session/copy")
    assert copied.status_code == 201
    exported = await auth_client.get("/api/adventures/sessions/portrait-session/export")
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("relationships.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200
    for session_id in (copied.json()["game_id"], imported.json()["game_id"]):
        card = (await auth_client.get(f"/api/adventures/{session_id}/npcs/{npc_id}")).json()
        assert card["relationship"] == expected
