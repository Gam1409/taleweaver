"""Compact lookup views retain authored knowledge without consuming budget with defaults."""

import json
from copy import deepcopy

import pytest

from backend.engine.chpm import agent_lookup_payload, authored_capabilities, inference
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.core.contracts import AuthoredTrait
from backend.engine.chpm.state import load
from tests.conftest import TestSessionLocal
from tests.test_chpm_authored_capabilities import ABILITY, DESCRIPTION, actor
from tests.test_chpm_host_state import mind
from tests.test_chpm_host_turn import run
from tests.test_chpm_kernel import observation
from tests.test_chpm_notebook_turn import (
    ACTION,
    NOTE,
    NotebookRoles,
    configure,
    install,
    row,
    stored,
)


def test_compact_lookup_preserves_original_card_text_binding_and_uncertainty_without_aliasing():
    full = authored_capabilities.project(actor())
    full["description_omitted_characters"] = 200
    full["omitted_abilities"] = 4
    full["abilities"][0]["omitted_characters"] = {"description": 90}
    before = deepcopy(full)
    compact = authored_capabilities.lookup_fields({authored_capabilities.KEY: full}, "npc")[
        authored_capabilities.KEY
    ]
    assert compact["actor_id"] == "npc"
    assert compact["description"] == DESCRIPTION
    assert compact["abilities"][0]["description"] == ABILITY["description"]
    assert compact["mechanical_execution"] is False
    assert compact["description_omitted_characters"] == 200
    assert compact["omitted_abilities"] == 4
    assert compact["abilities"][0]["omitted_characters"] == {"description": 90}
    assert compact["catalog_status"] == "available"
    assert set(compact).isdisjoint({"meaning", "scope", "source"})
    compact["abilities"][0]["name"] = "Changed transient lookup"
    assert full == before
    with pytest.raises(ValueError, match="observer"):
        authored_capabilities.lookup_fields({authored_capabilities.KEY: full}, "other")


@pytest.mark.parametrize("catalog", [None, "unreadable legacy catalog"])
def test_empty_lookup_catalog_is_unknown_not_a_claim_of_no_abilities(catalog):
    full = authored_capabilities.project(actor(metadata_json={"special_actions": catalog}))
    compact = authored_capabilities.lookup_fields({authored_capabilities.KEY: full}, "npc")[
        authored_capabilities.KEY
    ]
    assert compact["catalog_status"] == ("not_recorded" if catalog is None else "unavailable")
    assert compact["description"] == DESCRIPTION
    assert compact["mechanical_execution"] is False
    assert "abilities" not in compact
    assert "omitted_abilities" not in compact
    assert "description_omitted_characters" not in compact


def test_lookup_identity_keeps_all_authored_values_without_repeating_technical_defaults():
    value = mind()
    identity = value.genesis.identity.model_copy(
        update={
            "values": ("Protect the woodland",),
            "roles": ("Lantern keeper",),
            "traits": (AuthoredTrait(key="value", value="Curiosity"),),
        }
    )
    value = value.model_copy(
        update={"genesis": value.genesis.model_copy(update={"identity": identity})}
    )
    before = value.model_dump_json()
    observed = observation()
    body = agent_lookup_payload.build(value, observed, {}, Tools(value, observed, {}), 1, [])
    assert body["identity"] == {
        "description": identity.description,
        "authored_goals": list(identity.authored_goals),
        "values": ["Protect the woodland"],
        "roles": ["Lantern keeper"],
        "traits": [{"key": "value", "value": "Curiosity"}],
    }
    assert body["observer_id"] == value.genesis.scope.observer_id
    assert value.model_dump_json() == before


async def test_first_staged_notebook_lookup_keeps_own_card_within_existing_eight_thousand_limit(
    monkeypatch,
):
    roles = NotebookRoles(pages=True)
    install(monkeypatch, roles)
    measured = []
    original = inference.tool_request

    async def recording(manager, settings, usage, messages, tools, **kwargs):
        body = json.loads(
            next(message["content"] for message in messages if message["role"] == "user")
        )
        if not measured:
            mind = manager._chpm_turn.minds["LINA"]
            view = authored_capabilities.context_fields(
                {
                    authored_capabilities.KEY: authored_capabilities.project(
                        actor(id="LINA", description="A woman in a blue coat.", metadata_json={})
                    )
                },
                "LINA",
            )
            full = {**body, **view, "identity": mind.genesis.identity.model_dump(mode="json")}
            legacy = deepcopy(messages)
            next(message for message in legacy if message["role"] == "user")["content"] = (
                json.dumps(full, ensure_ascii=False)
            )
            sizing = kwargs["llm"].input_size
            measured.append((sizing(legacy, tools), sizing(messages, tools), body))
        return await original(manager, settings, usage, messages, tools, **kwargs)

    monkeypatch.setattr(inference, "tool_request", recording)
    async with TestSessionLocal() as db:
        user, state = await configure(db, max_input_chars=8000)
        db.add(row(user.id, {"long": NOTE + '\\"\n' * 20000}))
        await db.commit()
        _, events = await run(db, user, ACTION)
        before, after, first = measured[0]
        print(f"first_lookup_before={before} after={after} unchanged_budget=8000")
        assert before > 8000 and after <= 8000
        assert first[authored_capabilities.KEY]["description"] == "A woman in a blue coat."
        assert first[authored_capabilities.KEY]["actor_id"] == first["observer_id"] == "LINA"
        assert first[authored_capabilities.KEY]["mechanical_execution"] is False
        assert first["identity"]["description"] == "Values honesty."
        assert first["identity"]["authored_goals"] == ["SECRET_GOAL_NOT_PUBLIC"]
        assert any(event.startswith("event: error") for event in events)
        assert roles.chpm_calls == ["perception", "agent_lookup"]
        assert (await stored(db))[0].revision == 1
        await db.refresh(state)
        assert not load(state).actors and not load(state).minds
