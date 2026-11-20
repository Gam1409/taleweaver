"""The actor selects its stance and its own mechanical intent independently."""

from typing import Annotated, Literal

from pydantic import Field

from backend.engine.chpm.proposal_actions import _portable_union
from backend.engine.chpm.proposal_references import (
    ReferenceContract,
    ReferenceDevelopmentDraft,
    ReferenceDraft,
)
from backend.engine.npc_actions.selected_sources import Choice


class NoAction(ReferenceContract):
    mode: Literal["none"]
    steps: list[Choice] = Field(max_length=0)


class Act(ReferenceContract):
    mode: Literal["act"]
    steps: list[Choice] = Field(min_length=1, max_length=2)


PhysicalIntent = Annotated[
    NoAction | Act, Field(discriminator="mode", json_schema_extra=_portable_union)
]


class _PhysicalChoice(ReferenceContract):
    physical_intent: PhysicalIntent


class PhysicalDraft(ReferenceDraft, _PhysicalChoice):
    """Selected mechanical steps are actor-local proposals awaiting execution."""


class PhysicalDevelopmentDraft(ReferenceDevelopmentDraft, _PhysicalChoice):
    """The same execution contract when personal development is available."""


def wire_schema(development: bool) -> type[ReferenceDraft]:
    return PhysicalDevelopmentDraft if development else PhysicalDraft


INSTRUCTIONS = """
Choose physical_intent independently of your social choice. For the selected
candidate, use mode=act and one or two own phrases in steps, in order. Write
your intended physical conduct in your own words, not tool names or arguments.
A phrase may contain two successive acts; at most two supported actions total.
Optionally use {text, target_refs:[observed IDs]} instead of a string to identify
your referents. Use this when multiple visible items or participants could fit;
otherwise ambiguous targets cannot execute. Never invent IDs or choose another
participant's conduct. Inspect your view first when lookup rounds remain.
Only available_physical_commands can have persistent effects. Include offers
or uncertain/unsupported physical intentions honestly; the execution phase
distinguishes them from completed transfers. Speech, memories and negated or
future actions alone use mode=none, steps=[]. Refusal may accompany own action.
These selected words are private intentions, not world facts. Only publication
results establish completion; a recipient still chooses its own response.
"""
