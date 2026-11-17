"""Resolve transient model agenda IDs through the current owner's active ledger."""

from collections.abc import Sequence
from typing import Literal

from pydantic import ConfigDict, Field, TypeAdapter

from backend.engine.chpm import agenda
from backend.engine.chpm.core.contracts import Contract
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import AgendaEntry, AgendaIntent


class AgendaCreation(Contract):
    """New ongoing business needs newly authored text, without an existing ID."""

    model_config = ConfigDict(revalidate_instances="always")

    action: Literal["goal", "commitment"]
    text: str = Field(min_length=1, max_length=300)


class AgendaClosureReference(Contract):
    """An existing entry is addressed only by its active owned ID."""

    model_config = ConfigDict(revalidate_instances="always", str_strip_whitespace=False)

    action: Literal["withdraw", "report_done"]
    entry_id: str = Field(min_length=1, max_length=64)


AgendaReference = AgendaCreation | AgendaClosureReference
_REFERENCE: TypeAdapter[AgendaReference] = TypeAdapter(AgendaReference)


def active_ids(entries: Sequence[AgendaEntry], actor_id: str) -> list[str]:
    """Supply the decoder's entry_id allowlist without exposing another owner's ledger."""
    return [entry.id for entry in _owned_active(entries, actor_id)]


def materialize(
    intent: AgendaReference | None, entries: Sequence[AgendaEntry], actor_id: str
) -> AgendaIntent | None:
    """Derive canonical text after lookup in the caller's current source-reconciled entries."""
    if intent is None:
        return None
    wire = _REFERENCE.validate_python(intent)
    active = _owned_active(entries, actor_id)
    if isinstance(wire, AgendaCreation):
        canonical = AgendaIntent(action=wire.action, text=wire.text)
    else:
        target = next((entry for entry in active if entry.id == wire.entry_id), None)
        if target is None:
            raise ChpmError("CHPM agenda closure must identify an active owned entry exactly.")
        canonical = AgendaIntent(action=wire.action, entry_id=wire.entry_id, text=target.text)
    agenda.validate_intent(canonical, active)
    return canonical


def _owned_active(entries: Sequence[AgendaEntry], actor_id: str) -> list[AgendaEntry]:
    active = [entry for entry in entries if entry.actor_id == actor_id and entry.closure is None]
    if len(active) > agenda.MAX_ACTIVE or len({entry.id for entry in active}) != len(active):
        raise ChpmError(
            "CHPM agenda references require an unambiguous bounded active owned ledger."
        )
    return active
