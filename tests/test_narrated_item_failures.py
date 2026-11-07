"""Invalid item output is actionable without leaking provider data or losing the story."""

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.core.inference.registry import InferenceUncertainError
from backend.engine.narrated_items.diagnostics import describe_failure
from backend.engine.narrated_items.runtime import KEY
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.npc_presentation.settings import KEY as PORTRAIT_KEY
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn


def invalid_item_error():
    try:
        ItemExtraction.model_validate({"actions": [{"new_item": {"name": "Garment"}}]})
    except ValidationError as exc:
        wrapped = ValueError("Provider diagnostic with SECRET_API_KEY")
        wrapped.__cause__ = exc
        return wrapped
    raise AssertionError("Invalid garment unexpectedly passed validation")


def test_schema_exposes_distinct_new_and_existing_identities_to_the_model():
    schema = ItemExtraction.model_json_schema()
    choices = schema["properties"]["actions"]["items"]["anyOf"]
    assert len(choices) == 2
    existing = schema["$defs"]["ExistingItemAction"]
    new = schema["$defs"]["NewItemAction"]
    assert "item_id" in existing["required"]
    assert existing["properties"]["new_item"]["type"] == "null"
    assert "new_item" in new["required"]
    assert new["properties"]["item_id"]["type"] == "null"


@pytest.mark.parametrize(
    "error,code",
    [
        (TimeoutError("SECRET_API_KEY"), "timeout"),
        (InferenceUncertainError("SECRET_API_KEY"), "inference_uncertain"),
        (json.JSONDecodeError("SECRET_API_KEY", "SECRET_API_KEY", 0), "invalid_json"),
        (invalid_item_error(), "invalid_schema"),
        (RuntimeError("SECRET_API_KEY"), "unavailable"),
    ],
)
def test_failure_diagnostics_are_bounded_and_do_not_expose_provider_text(error, code):
    failure = describe_failure(error)
    assert failure.code == code
    assert "SECRET_API_KEY" not in failure.message()
    assert "SECRET_API_KEY" not in str(failure.payload())
    assert len(failure.validation_fields) <= 5


@pytest.mark.parametrize(
    "error,code", [(invalid_item_error(), "invalid_schema"), (TimeoutError(), "timeout")]
)
async def test_failed_item_check_retains_narration_emotions_and_both_owners(
    monkeypatch, error, code
):
    body = "Лина поправляет халат и смотрит на героя."
    raw = (
        body
        + "<npc-state>"
        + json.dumps(
            {
                "npcs": [
                    {
                        "npc_id": "LINA",
                        "emotion": "interest",
                        "intensity": 70,
                        "thought": "Нужно разобраться.",
                    }
                ]
            }
        )
        + "</npc-state>"
    )
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", raw)

    class BrokenItemRoles(TurnRoles):
        async def structured(self, *args, **kwargs):
            schema = kwargs.get("response_model") or args[2]
            if schema is ItemExtraction:
                raise error
            return await super().structured(*args, **kwargs)

    roles = BrokenItemRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        state.entity_states = {
            **state.entity_states,
            PORTRAIT_KEY: {
                "emotion_palette": True,
                "character_thoughts": True,
            },
        }
        await db.commit()
        inventory = list(avatar.inventory)
        from backend.engine.gameplay.manager import GameTurnManager

        events = [
            event async for event in GameTurnManager(db, "session-1", user).process_turn("Я жду.")
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        assert state.entity_states[KEY]["failure"]["code"] == code
        assert avatar.inventory == inventory
        messages = list(
            await db.scalars(select(ChatMessage).where(ChatMessage.session_id == "session-1"))
        )
        reply = next(message for message in messages if message.content == body)
        assert reply.to_client_dict()["portrait_state"]["npcs"]["LINA"]["intensity"] == 70
        assert "SECRET_API_KEY" not in "".join(events)
        assert "story was retained" in "".join(events)
        assert len(roles.prompts) == 1
