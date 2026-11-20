"""Advertise only available lookup surfaces without changing their authoritative guards."""

from typing import TYPE_CHECKING

from backend.engine.chpm import agent_observable, host_observations
from backend.engine.chpm.native_tool_contracts import known_tool_names, tool_definitions
from backend.engine.npc_actions.tool_schema import definitions as action_definitions

if TYPE_CHECKING:
    from backend.engine.chpm.agent_tools import Tools


def definitions(tools: "Tools") -> list[dict]:
    names = set(known_tool_names())
    if agent_observable.current(tools) is None:
        names -= {"find_entity", "inspect_scene"}
    facts = host_observations.previous(tools.mind)
    if not facts or not set(facts.visible_actor_ids).intersection(tools.clothing):
        names.discard("visible_clothing")
    draft = tools.current_actions()
    actions = action_definitions(draft.available_tools()) if draft is not None else []
    return [*tool_definitions(tools.notebook is not None, available_lookups=names), *actions]
