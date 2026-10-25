"""Named introductions become session entities; learned facts survive beyond chat context."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.engine.npc_journal import worker
from backend.engine.npc_journal.apply import apply_extraction
from backend.engine.npc_journal.records import journal_of, memory_context
from backend.engine.npc_journal.schema import CharacterObservation, JournalExtraction, Observation
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal
from tests.llm_fakes import RoleLLMFactory
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
INTRO = "Девушка сказала: «Меня зовут Мира». На ней синий плащ."
QUOTE = "Меня зовут Мира"


def introduction(name="Мира", quote=QUOTE, **kwargs):
    return CharacterObservation(name=name, self_introduction=quote, **kwargs)


def observation(category="appearance", text="Синий плащ", evidence="На ней синий плащ.", **kwargs):
    return Observation(category=category, text=text, evidence=evidence, source="observed", **kwargs)


@pytest_asyncio.fixture
async def journal_world(portrait_world, monkeypatch):
    async with TestSessionLocal() as db:
        db.add(
            WorldScene(
                id="TOWER", session_id="portrait-session", label="Башня", description="Башня"
            )
        )
        session = await db.get(GameSession, "portrait-session")
        session.content_language = "Russian"
        owner = session.user_id
        await db.commit()
    portraits = MagicMock()
    monkeypatch.setattr(worker, "schedule_portrait", portraits)
    return owner, portraits


async def save_message(content=INTRO, **kwargs):
    async with TestSessionLocal() as db:
        message = ChatMessage(
            session_id="portrait-session",
            role="assistant",
            content=content,
            scene_id="TOWER",
            npc_journal={"status": "pending"},
            **kwargs,
        )
        db.add(message)
        await db.commit()
        return message.id


async def apply(message_id, characters):
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        ids = await apply_extraction(db, message, JournalExtraction(characters=characters), "Hero")
        await db.commit()
        return ids


async def npc_by_id(npc_id):
    async with TestSessionLocal() as db:
        return await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session",
                WorldEntity.id == npc_id,
            )
        )


async def test_introduction_creates_minimal_session_owned_npc(journal_world):
    message_id = await save_message()
    ids = await apply(message_id, [introduction(aliases=["Девушка"], observations=[observation()])])

    assert len(ids) == 1 and ids[0].isascii()
    npc = await npc_by_id(ids[0])
    assert npc.name == "Мира" and npc.description == "Синий плащ"
    assert npc.template_id is None and npc.current_scene_id == "TOWER"
    assert npc.hp is None and npc.inventory == []
    assert journal_of(npc)["introduction"] == QUOTE
    assert journal_of(npc)["aliases"] == ["Девушка"]
    assert journal_of(npc)["entries"][0]["message_id"] == message_id


@pytest.mark.parametrize(
    "name,quote",
    [
        ("Mira", "My name is Mira"),
        ("明", "私は明です"),
        ("Lucía", "Me llamo Lucía"),
        ("Мира", "Меня зовут Мира"),
    ],
)
async def test_introductions_support_unicode_names(journal_world, name, quote):
    message_id = await save_message(quote)
    ids = await apply(message_id, [introduction(name, quote)])
    assert len(ids) == 1
    assert (await npc_by_id(ids[0])).name == name


@pytest.mark.parametrize(
    "candidate",
    [
        CharacterObservation(name="Мира"),
        introduction(quote="Меня зовут другая девушка"),
        introduction(quote="Мира"),
        introduction(npc_id="fabricated-id"),
        introduction(name="Hero", quote="My name is Hero"),
    ],
)
async def test_missing_or_fabricated_introduction_cannot_create_card(journal_world, candidate):
    message_id = await save_message(INTRO + " My name is Hero")
    assert await apply(message_id, [candidate]) == []


async def test_empty_extraction_does_not_turn_named_mentions_into_npcs(journal_world):
    message_id = await save_message("В письме написано: «Меня зовут Мира». Девушка ушла.")
    # Classification is the model's job. Empty extraction is the expected result for a letter.
    assert await apply(message_id, []) == []


async def test_repeat_and_alias_keep_identity_and_do_not_duplicate_history(journal_world):
    message_id = await save_message()
    npc_id = (await apply(message_id, [introduction(observations=[observation()])]))[0]
    assert await apply(message_id, [introduction(observations=[observation()])]) == []
    next_id = await save_message("Мира сказала: «Зови меня Искра».")
    assert await apply(next_id, [introduction("Искра", "Зови меня Искра", npc_id=npc_id)]) == []
    npc = await npc_by_id(npc_id)
    assert len(journal_of(npc)["entries"]) == 1
    assert "Искра" in journal_of(npc)["aliases"]


async def test_later_observations_append_history_and_keep_prior_knowledge(journal_world):
    first = await save_message()
    npc_id = (await apply(first, [introduction(observations=[observation(topic="coat")])]))[0]
    second = await save_message(
        "Мира надела красный плащ. «Я кузнец», — сказала она. Мира убрала кинжал в сумку."
    )
    changes = CharacterObservation(
        npc_id=npc_id,
        name="Мира",
        observations=[
            observation(text="Красный плащ", evidence="Мира надела красный плащ.", topic="coat"),
            Observation(
                category="background",
                topic="occupation",
                source="claimed",
                text="Говорит, что она кузнец",
                evidence="Я кузнец",
            ),
            observation(
                "belongings", "Кинжал в сумке", "Мира убрала кинжал в сумку.", topic="dagger"
            ),
        ],
    )
    await apply(second, [changes])
    npc = await npc_by_id(npc_id)
    assert len(journal_of(npc)["entries"]) == 4
    memory = memory_context(npc)
    assert "Красный" in memory and "Синий" not in memory
    assert "claimed" in memory and "кузнец" in memory
    assert "Кинжал" in memory
    assert npc.inventory == []  # Observations do not mint transferable gameplay items.
    assert "кузнец" not in memory_context(npc, visual_only=True)


async def test_unquoted_claims_are_not_saved(journal_world):
    message_id = await save_message()
    ids = await apply(
        message_id, [introduction(observations=[observation(evidence="She is the secret queen")])]
    )
    assert journal_of(await npc_by_id(ids[0]))["entries"] == []


async def test_existing_npc_updates_without_creating_template_or_session_duplicate(journal_world):
    message_id = await save_message('Lina says: "My name is Lina". Lina carries a lantern.')
    changes = introduction(
        "Lina",
        "My name is Lina",
        npc_id="NPC_NEW",
        observations=[
            observation(
                "belongings", "Carries a lantern", "Lina carries a lantern.", topic="lantern"
            )
        ],
    )
    assert await apply(message_id, [changes]) == []
    npc = await npc_by_id("NPC_NEW")
    assert npc.description == "Original description"
    assert len(journal_of(npc)["entries"]) == 1
    async with TestSessionLocal() as db:
        template = await db.scalar(
            select(WorldEntity).where(WorldEntity.session_id.is_(None), WorldEntity.id == "NPC_NEW")
        )
        assert "npc_journal" not in template.metadata_json


async def test_worker_uses_small_role_language_and_commits_before_portrait(
    journal_world, monkeypatch
):
    owner, portraits = journal_world
    message_id = await save_message()
    llm = MagicMock()
    llm.aexecute_complex_task = AsyncMock(
        return_value=JournalExtraction(characters=[introduction()])
    )
    factory = MagicMock(return_value=llm)
    monkeypatch.setattr("backend.engine.npc_journal.extract.GameMasterLLM", RoleLLMFactory(factory))
    assert await worker.process_message(message_id, owner)
    assert factory.call_args.kwargs["model_category"] == "small"
    args = llm.aexecute_complex_task.call_args.args
    assert "Russian" in args[0]
    assert json.loads(args[1])["current_narration"] == INTRO
    assert portraits.call_count == 1
    npc_id = portraits.call_args.args[1]
    assert await npc_by_id(npc_id)
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        assert message.npc_journal["status"] == "done"
    assert not await worker.process_message(message_id, owner)
    assert portraits.call_count == 1


async def test_worker_failure_preserves_narration_and_supports_retry(journal_world, monkeypatch):
    owner, portraits = journal_world
    message_id = await save_message()
    monkeypatch.setattr(
        worker, "extract", AsyncMock(side_effect=RuntimeError("private endpoint details"))
    )
    assert not await worker.process_message(message_id, owner)
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, message_id)
        assert message.content == INTRO
        assert message.npc_journal["status"] == "failed"
        assert "private endpoint" not in message.npc_journal["error"]
    portraits.assert_not_called()


async def test_worker_rejects_other_user(journal_world, monkeypatch):
    message_id = await save_message()
    model = AsyncMock()
    monkeypatch.setattr(worker, "extract", model)
    assert not await worker.process_message(message_id, "another-owner")
    model.assert_not_awaited()
