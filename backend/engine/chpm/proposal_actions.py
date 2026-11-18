"""Selected, actor-authored steps in a final submission use the existing command draft."""

from typing import Annotated

from pydantic import Field

from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.proposal_references import (
    ReferenceContract,
    ReferenceDevelopmentDraft,
    ReferenceDraft,
)
from backend.engine.chpm.schema import ActionKind
from backend.engine.npc_actions.contracts import Adjust, Give, Pose, PutDown, Take, TakeOff, Wear
from backend.engine.npc_actions.preview import Draft


def _portable_union(schema: dict) -> None:
    # The tool consts already discriminate every branch. Native and JSON adapters may
    # relocate definitions; an OpenAPI discriminator mapping would retain local paths.
    schema.pop("discriminator", None)


Step = Annotated[
    Take | Give | PutDown | Wear | TakeOff | Adjust | Pose,
    Field(discriminator="tool", json_schema_extra=_portable_union),
]


class AdditionalActions(ReferenceContract):
    for_choice: ActionKind
    steps: list[Step] = Field(min_length=1, max_length=2)


class _SelectedActions(ReferenceContract):
    additional_actions: AdditionalActions | None = Field(
        default=None,
        description="Up to two extra ordered own steps for your selected choice. Omit previously staged steps.",
    )


class ActionDraft(ReferenceDraft, _SelectedActions):
    pass


class ActionDevelopmentDraft(ReferenceDevelopmentDraft, _SelectedActions):
    pass


def wire_schema(development: bool, actions: bool) -> type[ReferenceDraft]:
    if actions:
        return ActionDevelopmentDraft if development else ActionDraft
    return ReferenceDevelopmentDraft if development else ReferenceDraft


def approve(draft: Draft, selected: ActionKind, extra: AdditionalActions | None) -> None:
    if extra is not None:
        if extra.for_choice != selected:
            raise ChpmError("additional_actions/for_choice must identify the selected choice.")
        try:
            draft.append_selected(extra.steps)
        except ValueError as exc:
            raise ChpmError(str(exc)) from exc
    draft.approved = True
