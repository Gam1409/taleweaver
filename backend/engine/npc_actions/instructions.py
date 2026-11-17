"""Guidance for the optional host-validated action surface."""

from collections.abc import Mapping

from backend.engine.npc_actions.contracts import ACTION_MODELS

INSTRUCTIONS = """
When action functions are offered, choose your own feasible actions from your
identity, motives and observed scene. You may act, decline, wait or reconsider;
activity and obedience are not requirements. Never decide a player's voluntary
response. Memory reads remain canonical current facts.
pending_actions_not_world_facts is your ordered plan, not history or a completed
outcome. Action functions return
staged previews, not applied facts; submission approves that plan for fresh host
checks. Read the results: a failed prerequisite did not happen. Use discard_actions
to abandon a plan before choosing a different course. Do not repeat successful
staging or notebook writes. Exact IDs come from current views/find_entity, never
invented names. Room travel ends this scene's action plan. Follow current custody,
coverage, resources and known routes. Descriptive state cannot grant capabilities,
invent quantities or replace identity. At zero remaining rounds submit your
grounded decision alone. The host reports which approved actions actually applied.
"""

SUBMISSION_ACTIONS = (
    "If you choose an inventory, wardrobe, item-state, posture, local-approach "
    "or room-travel change owned by an offered function, call that specific function before "
    "submitting. A candidate message_plan alone does not stage or execute these changes; "
    "the later narrator cannot supply omitted commands. Speech, waiting, refusal and "
    "no-action choices need no action call."
)


def submission(offered: list[dict]) -> str:
    """Place execution guidance at the terminal choice only while actions are offered."""
    description = "Submit this observer's complete proposal for host validation."
    actions = ACTION_MODELS.keys() - {"discard_actions"}
    if any(item["function"]["name"] in actions for item in offered):
        return description + " " + SUBMISSION_ACTIONS
    return description


RESOLUTION_CHRONOLOGY = (
    "\nhost_resolution/draft/outcome precedes authoritative_command_outcomes. Only status=applied "
    "overrides earlier exact owned fields; unrelated failures stay. Other/missing statuses prove no success.\n"
)

EXECUTION = """
authoritative_command_outcomes supplies complete publication results per
tool-controlled actor. An empty list means no command was executed by that
actor. A selected intention/message_plan is not execution. Narration cannot supply
omitted inventory, wardrobe, item-state, posture, local-approach or room-travel
changes. Review and correct claims of such voluntary completion against these
results. An empty plan is neither a physical failed attempt nor a requirement to
act or obey. Speech, waiting, refusal and no action remain valid. Compatible
gestures, emotional delivery and independent player, other-actor or world effects
remain eligible.
"""

NARRATION = (
    """
AUTHORITATIVE NPC COMMANDS: authoritative_command_outcomes lists host-checked
effects already attempted before this narration. Current state and applied effects
override pre-command observations and intentions.
Describe their compatible actions and emotional delivery without executing the
same effect twice or reversing its final state. Blocked/stale/skipped operations
did not complete; preserve successful earlier effects and leave missing outcomes
unknown. An attempted interaction establishes only the NPC's own attempt, never
recipient cooperation, a completed bodily change or mechanical success. Do not
invent another acquisition, wardrobe change or departure for a
tool-controlled actor outside its approved plan. Ordinary compatible gestures,
dialogue and independent physical consequences remain free. Preserve player agency.
"""
    + RESOLUTION_CHRONOLOGY
)


def resolution_timing(outcomes: Mapping[str, list[dict]]) -> dict[str, str]:
    """Label the existing earlier resolution without replacing its facts or failures."""
    return {"host_resolution_time": "before_command_publication"} if outcomes else {}


def for_outcomes(outcomes: Mapping[str, list[dict]]) -> str:
    """Use identical owner semantics for narration, review and bounded correction."""
    return _empty_instructions(outcomes) + NARRATION if outcomes else ""


def resolution_instructions(outcomes: Mapping[str, list[dict]]) -> str:
    """Give review and repair the same execution and temporal precedence rules."""
    return _empty_instructions(outcomes) + RESOLUTION_CHRONOLOGY if outcomes else ""


def _empty_instructions(outcomes: Mapping[str, list[dict]]) -> str:
    return EXECUTION if any(not rows for rows in outcomes.values()) else ""
