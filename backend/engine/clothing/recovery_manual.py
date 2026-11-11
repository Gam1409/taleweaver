"""User-authored recovery proposals share the existing source checks and apply path."""

import shlex
from types import SimpleNamespace
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.engine.clothing.body_schema import BodySlot
from backend.engine.clothing.context import detail_settings
from backend.engine.clothing.recovery_context import KEY, recovery_context
from backend.engine.clothing.recovery_correction import revise_preview
from backend.engine.clothing.recovery_evaluation import evaluated_preview
from backend.engine.clothing.recovery_payload import build_payload
from backend.engine.clothing.recovery_schema import RecoveryEntry, RecoveryGarment, RecoveryProposal
from backend.engine.narrated_items.schema import NewOrdinaryItem


class ManualDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_message_id: str = Field(min_length=1, max_length=100)
    evidence: str = Field(min_length=4, max_length=800)
    disposition: Literal["worn", "carried"]
    attachment_slot: BodySlot | None = None
    new_item: Annotated[RecoveryGarment | NewOrdinaryItem, Field(discriminator="kind")]


async def prepare_sources(
    db: Any, state: Any, args: str, user: Any = None, adventure: Any = None, avatar: Any = None
) -> str:
    if not state.is_debug_enabled or avatar is None:
        return "DEBUG ERROR: Manual recovery requires debug mode and a session avatar."
    try:
        parts = shlex.split(args)
        if len(parts) != 2:
            raise ValueError("Expected wardrobe_sources NPC_ID.")
        context = await recovery_context(db, state, avatar, parts[1])
        old = (state.entity_states or {}).get(KEY) or {}
        if (
            old.get("npc_id") == parts[1]
            and old.get("fingerprint") == context["fingerprint"]
            and old.get("proposal")
        ):
            return "DEBUG: Recovery sources ready; the existing preview was retained. No model request."
        detailed = detail_settings(SimpleNamespace(state=state))["detailed"]
        context, _ = build_payload(context, detailed)
        preview = {
            "npc_id": parts[1],
            "token": str(uuid4()),
            "fingerprint": context["fingerprint"],
            **evaluated_preview(context, RecoveryProposal(), detailed, state.session_id),
            "notes": "Manual recovery: choose a source passage and confirm the current state. No model request.",
            "messages_scanned": len(context["messages"]),
            "context_messages": len(context["messages"]),
            "limited": context["limited"],
            "model_step_started": False,
        }
    except ValueError as exc:
        return f"DEBUG ERROR: {exc}"
    state.entity_states = {**(state.entity_states or {}), KEY: preview}
    return "DEBUG: Recovery sources ready. No model request or inventory changes."


def _proposal(args: str, preview: dict) -> tuple[int, RecoveryProposal]:
    if not isinstance(preview.get("proposal"), dict) or not isinstance(preview.get("npc_id"), str):
        raise ValueError("Load the recovery sources before adding a proposal.")
    parts = args.split(maxsplit=2)
    if len(parts) != 3 or parts[1] != preview.get("token"):
        raise ValueError("Preview is missing or has been replaced. Load the sources again.")
    if len(parts[2]) > 40000:
        raise ValueError("Manual proposal is too large.")
    draft = ManualDraft.model_validate_json(parts[2])
    owner = preview["npc_id"]
    entry = RecoveryEntry.model_validate(
        {
            "source_message_id": draft.source_message_id,
            "action": {
                "source_owner": owner,
                "destination_owner": owner,
                "basis": "observed_wear" if draft.disposition == "worn" else "completed",
                **draft.model_dump(exclude={"source_message_id"}),
            },
        }
    )
    original = RecoveryProposal.model_validate(preview["proposal"])
    proposal = RecoveryProposal.model_validate(
        {**original.model_dump(), "entries": [*original.entries, entry]}
    )
    return len(original.entries), proposal


async def add_proposal(
    db: Any, state: Any, args: str, user: Any = None, adventure: Any = None, avatar: Any = None
) -> str:
    if not state.is_debug_enabled or avatar is None:
        return "DEBUG ERROR: Manual recovery requires debug mode and a session avatar."
    preview = (state.entity_states or {}).get(KEY) or {}
    try:
        index, proposal = _proposal(args, preview)
        reviewed = await revise_preview(db, state, avatar, preview, proposal, index)
    except ValidationError:
        return "DEBUG ERROR: Invalid manual proposal. Check the item, source, state and placement fields."
    except ValueError as exc:
        return f"DEBUG ERROR: {exc}"
    reviewed["manual_indices"] = [*preview.get("manual_indices", []), index]
    state.entity_states = {**state.entity_states, KEY: reviewed}
    return "DEBUG: Manual recovery proposal added. Review and explicitly select it before applying. No inventory changes."
