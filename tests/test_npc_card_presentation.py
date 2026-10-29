"""Cards reuse public facts and reveal social estimates only after explicit opt-in."""

from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.core.llm_router import GameMasterLLM
from backend.engine.npc_cards.presentation import recent_summary
from backend.engine.npc_cards.settings import SETTINGS_KEY
from backend.engine.visual_novel.schema import (
    CharacterState,
    Relationship,
    SocialMemory,
    SocialState,
)
from backend.engine.visual_novel.state import save_state
from backend.models.adventure_template import AdventureTemplate
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
URL = "/api/adventures/portrait-session/npcs/NPC_NEW"
EVIDENCE = "Лина отступила и попросила не трогать её."


def entry(index, text, topic="general", category="event", source="observed", **extra):
    return {
        "id": str(index),
        "message_id": f"M{index}",
        "recorded_at": f"2026-10-25T12:00:{index:02d}",
        "category": category,
        "topic": topic,
        "text": text,
        "evidence": text,
        "source": source,
        **extra,
    }


def test_summary_deduplicates_topics_and_keeps_four_recent_meaningful_facts():
    facts = [
        entry(1, "Зелёный плащ", category="appearance"),
        entry(2, "Приняла подарок", topic="gift"),
        entry(3, "Вернула подарок", topic="gift"),
        entry(
            4,
            "Обещает доверять",
            topic="relationship_player",
            category="relationship",
            source="claimed",
        ),
        entry(5, "Показала дверь", topic="door"),
        entry(6, "Показала дверь", topic="same_event"),
        entry(7, "Ушла из комнаты", topic="departure", goals=["secret"]),
        entry(8, "Скрытое содержимое сумки", category="belongings"),
        entry(9, "Тайная мысль", source="private"),
    ]
    before = deepcopy(facts)
    summary = recent_summary(facts)
    assert [fact["id"] for fact in summary] == ["7", "6", "4", "3"]
    assert summary[2]["source"] == "claimed"
    assert summary[2]["evidence"] == "Обещает доверять"
    assert "goals" not in summary[0]
    assert facts == before


async def configure(*, visible=False, mode="vn", observed=True, emotion_only=False):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        template = await db.get(AdventureTemplate, "portrait-template")
        template.rule_enforcement_mode = mode
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session", WorldEntity.id == "NPC_NEW"
            )
        )
        npc.character = "Private character core"
        npc.goal = "Private goal"
        npc.inventory = [{"id": "SECRET", "name": "Hidden possession"}]
        npc.metadata_json = {
            "npc_journal": {
                "entries": [
                    entry(
                        1,
                        "Вернула подарок",
                        topic="gift",
                        core="never expose",
                        inventory=["hidden"],
                    ),
                    entry(
                        2,
                        "Говорит, что доверяет",
                        topic="relationship_player",
                        category="relationship",
                        source="claimed",
                    ),
                ]
            }
        }
        character = CharacterState(
            core="Private character core",
            goals=["Private goal"],
            next_intention="withdraw",
            emotion="guarded",
            emotion_cause=EVIDENCE if observed else "",
            relationship=Relationship(trust=-2, tension=3),
            fingerprints=["private-fingerprint"],
        )
        if observed and not emotion_only:
            character.memories = [
                SocialMemory(
                    event_id="event",
                    source_message_id="SOURCE",
                    kind="boundary_violated",
                    evidence=EVIDENCE,
                )
            ]
        social = SocialState(
            characters={"NPC_NEW": character},
            reviewed_scene_message_ids=["SOURCE"] if observed else [],
        )
        state.entity_states = {**state.entity_states, SETTINGS_KEY: {"show_state": visible}}
        save_state(state, social)
        db.add(
            ChatMessage(
                id="SOURCE",
                session_id=state.session_id,
                role="assistant",
                scene_id="TOWER",
                content=EVIDENCE,
            )
        )
        await db.commit()


async def saved_state():
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        return deepcopy(state.entity_states)


async def set_visible(visible):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {**state.entity_states, SETTINGS_KEY: {"show_state": visible}}
        await db.commit()


async def test_cards_are_private_by_default_and_reuse_existing_language(
    auth_client, portrait_world, monkeypatch
):
    await configure()
    llm = MagicMock(side_effect=AssertionError("Reading a card must not call an LLM"))
    monkeypatch.setattr(GameMasterLLM, "for_role", llm)
    before = await saved_state()
    response = await auth_client.get(URL)
    assert response.status_code == 200
    card = response.json()
    assert card["state_visible"] is False and card["insights"] is None
    assert [fact["text"] for fact in card["summary"]] == [
        "Говорит, что доверяет",
        "Вернула подарок",
    ]
    assert card["summary"][0]["source"] == "claimed"
    for private in (
        "Private character core",
        "Private goal",
        "private-fingerprint",
        "Hidden possession",
        "never expose",
        "next_intention",
        "inventory",
    ):
        assert private not in response.text
    assert await saved_state() == before
    llm.assert_not_called()


async def test_opt_in_returns_only_sourced_estimates_without_mutating_state(
    auth_client, portrait_world, monkeypatch
):
    await configure(visible=True)
    llm = MagicMock(side_effect=AssertionError("Reading a card must not call an LLM"))
    monkeypatch.setattr(GameMasterLLM, "for_role", llm)
    before = await saved_state()
    card = (await auth_client.get(URL)).json()
    assert card["state_visible"] is True
    assert card["insights"] == {
        "available": True,
        "relationship": {"trust": -2, "affinity": 0, "respect": 0, "tension": 3},
        "emotion": "guarded",
        "evidence": EVIDENCE,
        "source_message_id": "SOURCE",
        "source_created_at": card["insights"]["source_created_at"],
        "newer_responses": 0,
    }
    assert await saved_state() == before
    await set_visible(False)
    hidden = (await auth_client.get(URL)).json()
    assert hidden["insights"] is None
    assert hidden["summary"] == card["summary"]
    after = await saved_state()
    assert after["__vn_state__"] == before["__vn_state__"]
    llm.assert_not_called()


@pytest.mark.parametrize("mode,observed", [("rpg", True), ("vn", False)])
async def test_non_vn_or_unobserved_profiles_do_not_invent_social_state(
    auth_client, portrait_world, mode, observed
):
    await configure(visible=True, mode=mode, observed=observed)
    card = (await auth_client.get(URL)).json()
    assert card["state_visible"] is True
    assert card["insights"] == {
        "available": False,
        "relationship": None,
        "emotion": None,
        "evidence": None,
        "source_message_id": None,
    }


async def test_observed_emotion_without_a_scoring_event_has_no_invented_scores(
    auth_client, portrait_world
):
    await configure(visible=True, emotion_only=True)
    insight = (await auth_client.get(URL)).json()["insights"]
    assert insight["available"] is True
    assert insight["emotion"] == "guarded" and insight["relationship"] is None
    assert insight["source_message_id"] == "SOURCE"


@pytest.mark.parametrize(
    "role,session_id,content",
    [
        ("user", "portrait-session", EVIDENCE),
        ("assistant", "other-session", EVIDENCE),
        ("assistant", "portrait-session", "Different passage"),
    ],
)
async def test_unverifiable_or_foreign_sources_do_not_reveal_social_state(
    auth_client, portrait_world, role, session_id, content
):
    await configure(visible=True)
    async with TestSessionLocal() as db:
        message = await db.get(ChatMessage, "SOURCE")
        message.role, message.session_id, message.content = role, session_id, content
        await db.commit()
    assert (await auth_client.get(URL)).json()["insights"]["available"] is False


async def test_directory_and_details_use_same_name_portrait_and_visibility(
    auth_client, portrait_world
):
    await configure(visible=True)
    async with TestSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session", WorldEntity.id == "NPC_NEW"
            )
        )
        npc.image_url = None
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {
            **state.entity_states,
            "NPC_NEW": {
                "name": "Лина",
                "description": "Текущий облик",
                "image_url": "/data/current.png",
            },
        }
        await db.commit()
    detail = (await auth_client.get(URL)).json()
    directory = (await auth_client.get("/api/adventures/portrait-session/npcs")).json()
    card = next(card for card in directory["characters"] if card["id"] == "NPC_NEW")
    for key in (
        "name",
        "description",
        "image_url",
        "portrait_status",
        "narrative_role",
        "state_visible",
    ):
        assert card[key] == detail[key]
    assert detail["portrait_status"] == "ready"
    assert detail["name"] == "Лина" and detail["description"] == "Текущий облик"
    assert (await auth_client.get("/api/adventures/other-session/npcs/NPC_NEW")).status_code == 404


async def test_unknown_hidden_npc_is_not_exposed_even_with_opt_in(auth_client, portrait_world):
    await configure(visible=True)
    async with TestSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session", WorldEntity.id == "NPC_NEW"
            )
        )
        npc.is_hidden = True
        npc.metadata_json = {}
        await db.commit()
    assert (await auth_client.get(URL)).status_code == 404


async def test_card_marks_old_emotion_even_when_newer_text_repeats_quote(
    auth_client, portrait_world
):
    from datetime import timedelta

    await configure(visible=True, emotion_only=True)
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        from backend.engine.visual_novel.state import load_state

        social = load_state(state)
        social.characters["NPC_NEW"].emotion_source_message_id = "SOURCE"
        social.reviewed_scene_message_ids.append("NEWER")
        save_state(state, social)
        source = await db.get(ChatMessage, "SOURCE")
        db.add(
            ChatMessage(
                id="NEWER",
                session_id=state.session_id,
                role="assistant",
                content=EVIDENCE,
                created_at=source.created_at + timedelta(minutes=1),
            )
        )
        await db.commit()
    insight = (await auth_client.get(URL)).json()["insights"]
    assert insight["source_message_id"] == "SOURCE"
    assert insight["newer_responses"] == 1
