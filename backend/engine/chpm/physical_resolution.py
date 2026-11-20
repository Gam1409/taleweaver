"""The existing execution request resolves selected own phrases, never other speakers."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from backend.core.llm_schema_compaction import schema_nodes
from backend.engine.chpm import json_contract
from backend.engine.chpm.proposal_actions import _portable_union
from backend.engine.npc_actions.contracts import WorldAction
from backend.engine.npc_actions.selected_sources import (
    NonEffect,
    PassageId,
    SourceContract,
    Unresolved,
)
from backend.engine.npc_actions.tool_schema import DESCRIPTIONS

Step = Annotated[WorldAction, Field(discriminator="tool", json_schema_extra=_portable_union)]


class Resolution(SourceContract):
    passage_id: PassageId
    disposition: Literal["action", "no_effect", "unresolved"]
    actions: tuple[Step, ...] = Field(default=(), max_length=2)
    reason: NonEffect | Unresolved | None = None
    remainder: NonEffect | None = None

    @model_validator(mode="after")
    def complete(self) -> "Resolution":
        if self.disposition == "action":
            if not self.actions or self.reason is not None:
                raise ValueError("An action group requires its operations and no refusal reason.")
            return self
        reasons = (
            {"offer", "past", "negated", "future", "incidental"}
            if self.disposition == "no_effect"
            else {"ambiguous", "unsupported_effect", "unavailable_target"}
        )
        if self.actions or self.remainder is not None or self.reason not in reasons:
            raise ValueError("An unresolved or non-effect phrase cannot carry world operations.")
        return self


class Resolutions(SourceContract):
    resolutions: tuple[Resolution, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def bounded_actions(self) -> "Resolutions":
        if sum(len(row.actions) for row in self.resolutions) > 2:
            raise ValueError("A selection permits at most two physical operations.")
        return self


def definition(available: set[str], identifiers: dict[str, list[str]] | None = None) -> list[dict]:
    schema = json_contract.response_schema(Resolutions, identifiers)
    actions = schema["$defs"]["Resolution"]["properties"]["actions"]["items"]
    actions["oneOf"] = [
        option
        for option in actions["oneOf"]
        if schema["$defs"][option["$ref"].split("/")[-1]]["properties"]["tool"]["const"]
        in available
    ]
    _reachable_definitions(schema)
    for body in schema["$defs"].values():
        tool = body.get("properties", {}).get("tool", {}).get("const")
        if tool in DESCRIPTIONS:
            body["description"] = DESCRIPTIONS[tool]
    return [
        {
            "type": "function",
            "function": {
                "name": "resolve_selected_steps",
                "description": "Account for every selected own phrase; propose no other conduct.",
                "parameters": schema,
            },
        }
    ]


def _reachable_definitions(schema: dict) -> None:
    definitions = schema.pop("$defs")
    pending = [schema]
    retained = {}
    while pending:
        current = pending.pop()
        for _, node in schema_nodes(current):
            node.pop("discriminator", None)
            reference = node.get("$ref", "").removeprefix("#/$defs/")
            if reference in definitions and reference not in retained:
                retained[reference] = definitions[reference]
                pending.append(definitions[reference])
    schema["$defs"] = retained


INSTRUCTION = """
Resolve only this actor's selected private phrases below. Use resolve_selected_steps
once, one group per pN, covering every phrase. The host owns actor, source binding
and order. You do not choose a new action, speaker, target or recipient response.
Use disposition=action only for current own supported conduct, with actions in
clause order (at most two actions total). A compound removal then completed
handover needs take_off_item then give_item; take then put down needs both steps.
Removal then OFFER/question 'will you take it?' needs only removal, remainder=offer.
Offering alone is no_effect/offer: ownership stays with the giver. Receiving a
gift never implies wearing it. Speech/promise about later is no_effect/future;
an immediate own act in this private intention may be action. Remembered/past,
negated and merely incidental expression are no_effect with the corresponding
reason. A player's/narrator's speech, quotation or hypothetical is no authority.
Unsupported persistent effects are unresolved/unsupported_effect, not interact
as a substitute. If any intended stable clause has no representation, mark its
whole phrase unresolved; do not silently omit it. Incidental hesitating needs no
world operation. Compound action plus non-effect must record its remainder.
Use only accessible references with the correct roles. Optional target_refs
disambiguate the selected referents; they never authorize another actor to act.
If multiple eligible referents remain, return unresolved/ambiguous rather than
guessing an ID. Unknown/hidden targets are unresolved/unavailable_target.
Each action is only a proposal: the host checks current owner preconditions and
publishes real outcomes later. Never assert an invented completion.
"""
