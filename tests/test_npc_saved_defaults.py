"""Historical RPG budgets stay readable while new authoring requires current admission."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm.schema import Settings
from backend.engine.chpm.state import KEY
from backend.engine.chpm.template_settings import initial_states, stored_defaults
from backend.engine.import_build_archive_template import build_archive_template
from backend.engine.import_build_blueprint_template import build_blueprint_template
from backend.engine.import_build_session_template import build_session_template
from backend.models.adventure_template import AdventureTemplate
from tests.conftest import TestSessionLocal
from tests.test_chpm_api import chpm_world, portrait_world

__all__ = ["chpm_world", "portrait_world"]
PATH = "/api/adventures/portrait-template"


def saved_combat_defaults():
    return {
        **Settings().model_dump(mode="json"),
        "control_scope": "combat_actions",
        "mode": "live",
        "actor_ids": ["NPC_NEW"],
        "workflow": "integrated",
        "action_tools": True,
        "agent_steps": 3,
        "max_calls_per_turn": 8,
    }


def test_saved_combat_defaults_initialize_without_rewriting_the_historical_budget():
    prefs = saved_combat_defaults()
    before = deepcopy(prefs)
    adventure = SimpleNamespace(
        rule_enforcement_mode="rpg", npc_personality_settings=prefs, living_world_settings=None
    )
    states = {"existing": {"hp": 12}}
    initialized = initial_states(adventure, states)
    assert initialized[KEY]["settings"] == prefs
    assert initialized[KEY]["minds"] == {}
    assert initialized[KEY]["usage"]["calls"] == 0
    assert states == {"existing": {"hp": 12}} and prefs == before


@pytest.mark.parametrize("builder", ["blueprint", "archive", "session"])
def test_saved_combat_defaults_import_without_an_automatic_budget_increase(builder):
    prefs = saved_combat_defaults()
    raw = {
        "title": "Existing combat defaults",
        "rule_enforcement_mode": "rpg",
        "npc_personality_settings": prefs,
    }
    if builder == "blueprint":
        copied = build_blueprint_template({}, raw, raw, "owner", None, "rpg", False)
    elif builder == "archive":
        copied = build_archive_template("copy", "owner", raw, raw, None, "rpg", False, None, None)
    else:
        copied = build_session_template({"adventure": raw}, SimpleNamespace(id="owner"), None)
    assert copied.npc_personality_settings == prefs
    assert initial_states(copied, {})[KEY]["settings"] == prefs


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_ids": ["NPC_NEW", "NPC_NEW"]},
        {"max_calls_per_turn": 2},
        {"agent_steps": 1.5},
        {"unexpected": True},
        {"workflow": "staged"},
    ],
)
def test_saved_combat_compatibility_keeps_structural_and_historical_budget_validation(changes):
    with pytest.raises(ValueError):
        stored_defaults({**saved_combat_defaults(), **changes}, mode="rpg", preserve_saved=True)


def test_new_combat_authoring_requires_the_current_full_command_budget():
    with pytest.raises(ValueError, match="repair reserve"):
        stored_defaults(saved_combat_defaults(), mode="rpg")


async def test_existing_combat_budget_survives_unrelated_updates_but_new_authoring_rechecks_it(
    auth_client, chpm_world
):
    prefs = saved_combat_defaults()
    async with TestSessionLocal() as db:
        adventure = await db.get(AdventureTemplate, "portrait-template")
        adventure.rule_enforcement_mode = "rpg"
        adventure.npc_personality_settings = prefs
        await db.commit()
    unrelated = await auth_client.patch(PATH, json={"living_world_settings": {}})
    assert unrelated.status_code == 200, unrelated.text
    assert unrelated.json()["npc_personality_settings"] == prefs
    unchanged = await auth_client.patch(
        PATH,
        json={
            "title": "An unrelated editor save",
            "rule_enforcement_mode": "rpg",
            "npc_personality_settings": prefs,
        },
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["npc_personality_settings"] == prefs
    authored = await auth_client.patch(
        PATH, json={"npc_personality_settings": {**prefs, "max_output_tokens": 1400}}
    )
    assert authored.status_code == 422, authored.text
    assert (await auth_client.get(PATH)).json()["npc_personality_settings"] == prefs
