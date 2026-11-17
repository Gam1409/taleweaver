"""Own authored abilities inform VN decisions without publishing private cards or combat effects."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.chpm import context, host_adapter
from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.state import load
from backend.models.avatar import Avatar
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.observable_state_support import tools_for, world
from tests.test_chpm_host_state import mind
from tests.test_chpm_host_turn import run
from tests.test_chpm_native_notebook_loop import call, turn
from tests.test_chpm_native_notebook_turn import initial_payload
from tests.test_chpm_notebook_turn import ACTION, configure, install, succeeded
from tests.test_chpm_turn import ChpmRoles

DESCRIPTION = "She can kindle a pale lantern flame without a match."
ABILITY = {
    "id": "moonlight",
    "name": "Moonlight veil",
    "description": "A quiet veil of light conceals her outline in darkness.",
    "script": "PRIVATE_ABILITY_SCRIPT",
    "unlock_guard_expression": "PRIVATE_ABILITY_GUARD",
    "effects": [{"stat": "hp", "amount": "-100"}],
    "private_notes": {"hidden": "PRIVATE_NESTED_METADATA"},
}


def actor(**changes):
    return SimpleNamespace(
        **{
            "id": "npc",
            "name": "Lina",
            "description": DESCRIPTION,
            "character": "Changed card personality must not replace the pinned identity.",
            "metadata_json": {"special_actions": [deepcopy(ABILITY)]},
            **changes,
        }
    )


async def test_live_actor_view_keeps_own_authored_abilities_without_replacing_pinned_identity():
    value = mind()
    before = value.model_dump_json()
    original = actor()
    supplied = await context.actor_context(
        SimpleNamespace(state=SimpleNamespace(entity_states={})),
        host_adapter.actor_view(original, value),
        None,
    )
    view = supplied["own_authored_capabilities"]
    assert view["actor_id"] == "npc"
    assert view["description"] == DESCRIPTION
    assert view["abilities"][0]["name"] == ABILITY["name"]
    assert view["abilities"][0]["description"] == ABILITY["description"]
    assert view["mechanical_execution"] is False
    assert supplied["authored_character"] == value.genesis.identity.description
    assert "PRIVATE_" not in json.dumps(view)
    assert set(view["abilities"][0]).isdisjoint(
        {"effects", "cost", "script", "unlock_guard_expression"}
    )
    assert original.metadata_json["special_actions"][0] == ABILITY
    assert value.model_dump_json() == before


def test_card_projection_preserves_narrative_only_entries_and_reports_every_omission():
    from backend.engine.chpm.authored_capabilities import MAX_VIEW_CHARS, project

    original = actor(
        description="Ж" * 12000,
        metadata_json={
            "special_actions": [
                {"name": "Weave rain", "description": "Can persuade rain to fall gently."},
                {"id": "a" * 300, "name": "N" * 500, "description": "D" * 4000},
                {"name": {"script": "DO_NOT_STRINGIFY_OBJECTS"}},
                *[deepcopy(ABILITY) for _ in range(50)],
            ]
        },
    )
    before = deepcopy(vars(original))
    view = project(original)
    assert len(json.dumps(view, ensure_ascii=False)) <= MAX_VIEW_CHARS
    assert view["description"] == original.description[: len(view["description"])]
    assert view["description_omitted_characters"] == len(original.description) - len(
        view["description"]
    )
    assert view["abilities"][0] == {
        "name": "Weave rain",
        "description": "Can persuade rain to fall gently.",
        "omitted_characters": {},
    }
    assert "id" not in view["abilities"][0]
    assert view["abilities"][1]["omitted_characters"]["description"] > 0
    assert view["omitted_abilities"] == 53 - len(view["abilities"])
    assert "DO_NOT_STRINGIFY_OBJECTS" not in json.dumps(view)
    assert "hp" not in str(view) and "ATTACK" not in str(view)
    assert vars(original) == before


def test_legacy_empty_card_omits_optional_view_and_mismatched_observer_cannot_borrow_a_card():
    from backend.engine.chpm.authored_capabilities import project

    assert project(actor(description="", metadata_json={})) is None
    assert project(actor(description="", metadata_json={"special_actions": []})) is None
    with pytest.raises(ValueError, match="observer"):
        host_adapter.actor_view(actor(id="other"), mind())


def test_description_json_escaping_is_included_in_the_total_view_budget():
    from backend.engine.chpm.authored_capabilities import MAX_VIEW_CHARS, project

    original = actor(description="\x00" * 12000, metadata_json={})
    view = project(original)
    assert len(json.dumps(view, ensure_ascii=False)) <= MAX_VIEW_CHARS
    assert view["description_omitted_characters"] == len(original.description) - len(
        view["description"]
    )


def test_lookup_handoff_cannot_borrow_another_observers_card_or_alias_its_data():
    from backend.engine.chpm.authored_capabilities import KEY, context_fields, project

    own = project(actor())
    selected = context_fields({KEY: own}, "npc")
    selected[KEY]["abilities"][0]["name"] = "Modified transient view"
    assert own["abilities"][0]["name"] == ABILITY["name"]
    with pytest.raises(ValueError, match="observer"):
        context_fields({KEY: own}, "other")


def test_oversized_fixed_identity_cannot_loop_or_silently_truncate_the_observer_id():
    from backend.engine.chpm.authored_capabilities import MAX_VIEW_CHARS, project

    original = actor(id="К" * (MAX_VIEW_CHARS + 1), description="Own card.")
    with pytest.raises(ValueError, match="budget; no identity was truncated"):
        project(original)
    assert len(original.id) == MAX_VIEW_CHARS + 1


def test_public_entity_reads_never_publish_own_other_or_player_authored_ability_catalogs():
    manager, rows = world()
    rows[0].description, rows[0].metadata_json = DESCRIPTION, {"special_actions": [ABILITY]}
    rows[1].metadata_json = {"special_actions": [{"name": "OTHER_HIDDEN_MAGIC"}]}
    manager.avatar.stats = {
        "special_actions": [{"name": "HERO_HIDDEN_MAGIC"}],
        "unlocked_actions": ["HERO_UNLOCK"],
    }
    tools = tools_for(manager, rows)
    for identifier in ("npc", "other", "@player"):
        result = tools.execute(Lookup(tool="inspect_entity", argument=identifier))
        assert result["status"] == "ok"
        assert "special_actions" not in result["text"]
        assert "HIDDEN_MAGIC" not in result["text"]
        assert DESCRIPTION not in result["text"]
    assert all("HIDDEN_MAGIC" not in source.text for source in tools.mind.sources.values())


class KnowledgeRoles(ChpmRoles):
    def __init__(self):
        super().__init__()
        self.tool_payloads = []

    def for_role(self, *args, **kwargs):
        model = super().for_role(*args, **kwargs)
        model.aexecute_tool_turn = self.native
        return model

    async def native(self, messages, _tools, model, **kwargs):
        body = initial_payload(messages)
        self.tool_payloads.append(deepcopy(body))
        self.chpm_calls.append(kwargs["phase"])
        if kwargs["phase"] == "agent_lookup":
            return turn()
        return turn(call("decision", "submit_decision", await self.proposal(body, model)))

    async def proposal(self, body, model):
        raw = await super().simple("", json.dumps(body), model, phase="proposal")
        self.chpm_calls.pop()  # Reuse the existing offline proposal builder, no model request.
        return json.loads(raw)

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") not in {"agent_lookup", "integrated_decision"}:
            return await super().simple(system, payload, model, **kwargs)
        body = json.loads(payload)
        self.tool_payloads.append(deepcopy(body))
        self.chpm_calls.append(kwargs["phase"])
        if kwargs["phase"] == "agent_lookup":
            return json.dumps({"requests": []})
        return json.dumps(
            {
                "requests": [
                    {"name": "submit_decision", "arguments": await self.proposal(body, model)}
                ]
            }
        )


@pytest.mark.parametrize("workflow", ["staged", "integrated"])
@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_actual_vn_tool_and_decision_requests_receive_only_own_authored_knowledge(
    monkeypatch,
    workflow,
    protocol,
):
    roles = KnowledgeRoles()
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await configure(
            db, workflow=workflow, tool_protocol=protocol, agent_steps=1, max_input_chars=48000
        )
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.id == "LINA", WorldEntity.session_id == "session-1"
            )
        )
        npc.description, npc.metadata_json, npc.mana = (
            DESCRIPTION,
            {"special_actions": [deepcopy(ABILITY)]},
            17,
        )
        other = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.id == "ABSENT", WorldEntity.session_id == "session-1"
            )
        )
        other.metadata_json = {"special_actions": [{"name": "OTHER_HIDDEN_MAGIC"}]}
        hero = await db.get(Avatar, state.avatar_id)
        hero.stats = {
            **(hero.stats or {}),
            "special_actions": [{"name": "HERO_HIDDEN_MAGIC"}],
            "unlocked_actions": ["HERO_UNLOCK"],
        }
        before = deepcopy(hero.stats), hero.hp, hero.exp
        await db.commit()
        manager, events = await run(db, user, ACTION)
        succeeded(events)
        assert len(roles.tool_payloads) == len(roles.proposal_inputs) == 1
        for supplied in [*roles.tool_payloads, *roles.proposal_inputs]:
            view = supplied["own_authored_capabilities"]
            assert view["description"] == DESCRIPTION
            assert view["abilities"][0]["description"] == ABILITY["description"]
            assert not view["mechanical_execution"]
            serialized = json.dumps(supplied)
            assert "HIDDEN_MAGIC" not in serialized and "HERO_UNLOCK" not in serialized
            assert (
                "PRIVATE_ABILITY" not in serialized and "PRIVATE_NESTED_METADATA" not in serialized
            )
        saved = load(manager.state)
        assert saved.minds["LINA"].genesis.identity.description == "Values honesty."
        assert saved.usage.calls == (3 if workflow == "integrated" else 4)
        assert "own_authored_capabilities" not in saved.model_dump_json()
        assert DESCRIPTION not in saved.model_dump_json()
        await db.refresh(npc)
        await db.refresh(hero)
        assert npc.mana == 17 and npc.metadata_json["special_actions"] == [ABILITY]
        assert (hero.stats, hero.hp, hero.exp) == before
