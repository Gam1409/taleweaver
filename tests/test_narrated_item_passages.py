"""Source references select original text; they never repair or invent a quotation."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.narrated_items.runtime import KEY, reconcile_items
from backend.engine.narrated_items.schema import ItemExtraction, SharedItemExtraction
from backend.engine.physical_conditions.ledger import read
from backend.engine.physical_conditions.runtime import finish
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.engine.visual_novel.continuity import PLAYER
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn

TEXT = "Лина передала герою синий шарф. На ткани расплылось пятно чернил."


@pytest.mark.parametrize("staging", [False, True])
async def test_current_passage_ids_become_exact_saved_evidence(monkeypatch, staging):
    import json

    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        npc.inventory = [
            {"id": "SCARF", "name": "Синий шарф", "description": "Синий шерстяной шарф."}
        ]
        write_settings(state, VnSettings(scene_staging=staging))
        await db.commit()
        calls = []

        async def response(_instructions, payload, schema, *_args, **_kwargs):
            value = json.loads(payload)
            calls.append(value)
            passages = value["completed_narration"]
            assert isinstance(passages, dict)
            assert all(text in TEXT for text in passages.values())
            return schema.model_validate(
                {
                    "actions": [
                        {
                            "item_id": "SCARF",
                            "source_owner": "LINA",
                            "destination_owner": PLAYER,
                            "disposition": "carried",
                            "basis": "completed",
                            "evidence": next(iter(passages)),
                        }
                    ],
                    "condition_updates": [
                        {
                            "operation": "record",
                            "target_id": "SCARF",
                            "kind": "contamination",
                            "part": "fabric",
                            "detail": "Пятно чернил.",
                            "evidence": list(passages)[1],
                        }
                    ],
                }
            )

        monkeypatch.setattr(
            "backend.engine.narrated_items.runtime.GameMasterLLM.for_role",
            lambda *_: SimpleNamespace(model="local", aexecute_complex_task=response),
        )
        manager = SimpleNamespace(
            db=db,
            user=user,
            avatar=avatar,
            state=state,
            game_id=state.session_id,
            _vn_player_message_id="CURRENT",
        )
        await reconcile_items(manager, TEXT, completed=True, resolution="")
        message = ChatMessage(
            session_id=state.session_id, role="assistant", content=TEXT, scene_id="START"
        )
        db.add(message)
        await db.flush()
        assert finish(manager, message) == []
        await db.commit()
        await db.refresh(state)
        assert len(calls) == 1
        assert (
            state.entity_states[KEY]["accepted"][0]["evidence"] == "Лина передала герою синий шарф."
        )
        condition = next(iter(read(state.entity_states).conditions.values()))
        assert condition.origin.quote == "На ткани расплылось пятно чернил."
        assert condition.origin.message_id == message.id
        assert [item["id"] for item in avatar.inventory] == ["SCARF"]


@pytest.mark.parametrize(
    "quote", ["passage:p999", "The cloth was stained.", "На ткани...пятно чернил."]
)
def test_unrecognized_reference_and_paraphrase_remain_unconfirmed(quote):
    from backend.engine.narrated_items import evidence

    value = ItemExtraction(
        condition_updates=[
            {
                "operation": "record",
                "target_id": "SCARF",
                "kind": "contamination",
                "part": "fabric",
                "detail": "Ink.",
                "evidence": quote,
            }
        ]
    )
    resolved = evidence.bind(value, TEXT)
    assert resolved.condition_updates[0]["evidence"] == quote


def test_source_reference_cannot_borrow_another_message_or_mutate_original():
    from backend.engine.narrated_items import evidence

    value = SharedItemExtraction(
        condition_updates=[
            {
                "operation": "record",
                "target_id": "SCARF",
                "kind": "contamination",
                "part": "fabric",
                "detail": "Ink.",
                "evidence": "passage:p1",
            }
        ]
    )
    resolved = evidence.bind(value, TEXT)
    assert resolved.condition_updates[0]["evidence"] in TEXT
    assert value.condition_updates[0]["evidence"] == "passage:p1"
    assert (
        evidence.bind(value, "A different message.").condition_updates[0]["evidence"]
        == "passage:p1"
    )


@pytest.mark.parametrize(
    "text",
    [
        "Лина передала шарф Мики. На ткани осталось пятно чернил.",
        "Синий шёлк скользнул из её пальцев в ладони Мики; та бережно приняла свёрток.",
        "«Сбереги», — выдохнула Лина. Шарф оказался у Мики, а чернильная клякса — всё ещё на шёлке.",
        "Лина смотрела на шарф. "
        + "В свете лампы нити казались золотыми, хотя оставались синими. " * 20,
    ],
)
def test_literary_source_passages_preserve_original_words_and_punctuation(text):
    from backend.engine.narrated_items import evidence

    table = evidence.passages(text)
    assert table and all(0 < len(quote) <= 600 and quote in text for quote in table.values())
    reference = next(key for key, quote in table.items() if len(quote) >= 4)
    proposal = ItemExtraction(
        condition_updates=[
            {
                "operation": "record",
                "target_id": "SCARF",
                "kind": "contamination",
                "part": "fabric",
                "detail": "An independently proposed detail; this test checks source fidelity only.",
                "evidence": reference,
            }
        ]
    )
    assert evidence.bind(proposal, text).condition_updates[0]["evidence"] == table[reference]
