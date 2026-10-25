"""Two public history tabs and biography reuse facts without another model request."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.core.llm_router import GameMasterLLM
from backend.engine.npc_cards.presentation import character_overview, recent_summary
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_npc_card_presentation import URL, entry
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


async def save_entries(entries):
    async with TestSessionLocal() as db:
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session", WorldEntity.id == "NPC_NEW"
            )
        )
        npc.metadata_json = {"npc_journal": {"entries": entries}}
        npc.goal = "Hidden goal"
        npc.inventory = [{"id": "SECRET", "name": "Hidden inventory"}]
        await db.commit()


def test_overview_selects_latest_three_background_topics_and_keeps_claims():
    facts = [
        entry(1, "Работала учителем", category="background", topic="occupation", source="claimed"),
        entry(
            2, "Теперь работает врачом", category="background", topic="occupation", source="claimed"
        ),
        entry(3, "Родилась в Киото", category="background", topic="hometown", source="claimed"),
        entry(4, "Из семьи часовщиков", category="background", topic="family", source="claimed"),
        entry(5, "Любит старые книги", category="background", topic="interests", source="observed"),
        entry(6, "Синий плащ", category="appearance"),
        entry(7, "Получила письмо", category="event"),
    ]
    overview = character_overview(facts)
    assert [item["id"] for item in overview] == ["5", "4", "3"]
    assert [item["source"] for item in overview] == ["observed", "claimed", "claimed"]
    assert overview[1]["evidence"] == "Из семьи часовщиков"
    assert [item["id"] for item in character_overview(facts[:3])] == ["3", "2"]


def test_summary_excludes_relationships_with_other_people():
    facts = [
        entry(1, "Вернула герою книгу", category="event", topic="book"),
        entry(2, "Доверяет герою", category="relationship", topic="relationship_player"),
        entry(3, "Не доверяет мэру", category="relationship", topic="relationship_mayor"),
    ]
    assert [item["id"] for item in recent_summary(facts)] == ["2", "1"]


async def test_tab_categories_counts_and_overview_are_consistent(
    auth_client, portrait_world, monkeypatch
):
    llm = MagicMock(side_effect=AssertionError("History must never call a model"))
    monkeypatch.setattr(GameMasterLLM, "for_role", llm)
    facts = [
        entry(1, "Она врач", category="background", source="claimed"),
        entry(2, "Синий плащ", category="appearance"),
        entry(3, "Видели медальон", category="belongings"),
        entry(4, "На ней фартук", category="equipment"),
        entry(5, "Её брат — Акира", category="relationship", topic="brother", source="claimed"),
        entry(6, "Передала герою книгу", category="event", inventory=["Do not expose"]),
        entry(
            7,
            "Говорит, что доверяет герою",
            category="relationship",
            topic="relationship_player",
            source="claimed",
        ),
    ]
    await save_entries(facts)
    general = (await auth_client.get(URL, params={"history": "general"})).json()
    shared = (await auth_client.get(URL, params={"history": "shared"})).json()
    all_history = (await auth_client.get(URL)).json()
    assert [item["id"] for item in general["entries"]] == ["5", "4", "3", "2", "1"]
    assert [item["id"] for item in shared["entries"]] == ["7", "6"]
    assert [item["id"] for item in all_history["entries"]] == ["7", "6", "5", "4", "3", "2", "1"]
    for card in (general, shared, all_history):
        assert card["history_counts"] == {"general": 5, "shared": 2}
        assert card["overview"][0]["text"] == "Она врач"
        assert card["overview"][0]["source"] == "claimed"
        assert [item["id"] for item in card["summary"]] == ["7", "6"]
        assert card["has_more"] is False
        assert "Hidden goal" not in str(card) and "Hidden inventory" not in str(card)
        assert "Do not expose" not in str(card)
    assert general["history_kind"] == "general" and shared["history_kind"] == "shared"
    assert all_history["history_kind"] == "all"
    llm.assert_not_called()


@pytest.mark.parametrize("history", ["general", "shared"])
async def test_pagination_filters_before_offset_and_never_drops_the_other_tab(
    auth_client, portrait_world, history
):
    facts = []
    for index in range(120):
        facts.append(
            entry(
                index,
                f"記録 {index}",
                topic=f"fact_{index}",
                category="background" if index % 2 == 0 else "event",
                recorded_at=(datetime(2026, 10, 25) + timedelta(seconds=index)).isoformat(),
            )
        )
    await save_entries(facts)
    first = (await auth_client.get(URL, params={"history": history})).json()
    second = (await auth_client.get(URL, params={"history": history, "offset": 50})).json()
    expected = list(
        reversed(
            [
                item["id"]
                for item in facts
                if (item["category"] == "background") == (history == "general")
            ]
        )
    )
    assert first["history_counts"] == second["history_counts"] == {"general": 60, "shared": 60}
    assert len(first["entries"]) == 50 and first["has_more"] is True
    assert len(second["entries"]) == 10 and second["has_more"] is False
    assert [item["id"] for item in first["entries"] + second["entries"]] == expected
    assert first["overview"] == second["overview"]
    assert first["summary"] == second["summary"]
    assert first["entries"][0]["text"].startswith("記録")


async def test_empty_history_tab_and_invalid_filters(auth_client, portrait_world):
    await save_entries([entry(1, "Герой вернул книгу", category="event")])
    general = (await auth_client.get(URL, params={"history": "general"})).json()
    assert general["entries"] == [] and general["has_more"] is False
    assert general["overview"] == []
    assert general["history_counts"] == {"general": 0, "shared": 1}
    beyond = (await auth_client.get(URL, params={"history": "shared", "offset": 500})).json()
    assert beyond["entries"] == [] and beyond["has_more"] is False
    assert len(beyond["summary"]) == 1
    assert (await auth_client.get(URL, params={"history": "secret"})).status_code == 422
    assert (
        await auth_client.get(URL, params={"history": "general", "offset": -1})
    ).status_code == 422
