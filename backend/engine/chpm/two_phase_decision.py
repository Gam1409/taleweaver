"""The actor selects its stance and its own mechanical intent independently."""

from typing import Annotated, Literal

from pydantic import Field

from backend.engine.chpm.proposal_actions import _portable_union
from backend.engine.chpm.proposal_references import (
    ReferenceContract,
    ReferenceDevelopmentDraft,
    ReferenceDraft,
)
from backend.engine.npc_actions.contracts import WorldAction

Step = Annotated[WorldAction, Field(discriminator="tool", json_schema_extra=_portable_union)]


class NoAction(ReferenceContract):
    mode: Literal["none"]
    steps: list[Step] = Field(max_length=0)


class Act(ReferenceContract):
    mode: Literal["act"]
    steps: list[Step] = Field(min_length=1, max_length=2)


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
candidate only, put every own world change you choose NOW in mode=act with one
or two ordered command objects using exact observed IDs and final operands.
Speech or refusal can accompany an action of your own. Include the physical
step whenever you choose to perform one in this turn.
Use mode=none and steps=[] for speech, expression, waiting or a future plan.
The host requests those specific operations separately. Story text, inspecting
a target and submitting this intention cannot perform them. Do not choose for
another participant or invent IDs. You may inspect your view when lookup
rounds remain. Only actual publication results establish completion.
"""
