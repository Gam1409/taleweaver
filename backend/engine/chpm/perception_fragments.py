"""Account for every input fragment; classification remains a fallible model task."""

from typing import Literal

from pydantic import Field

from backend.engine.chpm import passages
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Contract, Perception

MAX_FRAGMENTS = 32
MAX_OBSERVED_CHARS = 6000
KINDS = Literal[
    "speech", "attempt", "action", "intention", "incidental", "private", "unobserved", "uncertain"
]
PUBLIC = {"speech", "attempt", "action", "intention", "incidental"}


class Fragment(Contract):
    kind: KINDS
    observers: list[str] = Field(max_length=20)
    engaged: list[str] = Field(default_factory=list, max_length=20)


class Projection(Contract):
    fragments: dict[str, Fragment] = Field(max_length=MAX_FRAGMENTS)


def index(message: str) -> dict[str, str]:
    if len(message) > MAX_OBSERVED_CHARS:
        raise ChpmError("CHPM perception input exceeds 6000 characters; no fragments were dropped.")
    result = passages.index(message)
    if len(result) > MAX_FRAGMENTS:
        raise ChpmError(
            "CHPM perception needs more than 32 fragments; split this dense message. No fragments were dropped."
        )
    # The splitter may remove whitespace, never non-whitespace source content.
    if "".join("".join(result.values()).split()) != "".join(message.split()):
        raise ChpmError("CHPM could not index the complete perception source.")
    return result


def resolve(raw: Projection, available: dict[str, str], names: set[str]) -> dict[str, Perception]:
    if set(raw.fragments) != set(available):
        raise ChpmError("CHPM perception must classify every fragment exactly once.")
    for entry in raw.fragments.values():
        observers, engaged = set(entry.observers), set(entry.engaged)
        if len(observers) != len(entry.observers) or len(engaged) != len(entry.engaged):
            raise ChpmError("CHPM perception repeats an observer.")
        if not observers <= names or not engaged <= names:
            raise ChpmError("CHPM perception names an unavailable observer.")
        if entry.kind not in PUBLIC and observers:
            raise ChpmError("CHPM perception exposed a private, unobserved or uncertain fragment.")
        if entry.kind in {"private", "unobserved"} and engaged:
            raise ChpmError("CHPM private text cannot establish outward engagement.")
        if entry.kind in PUBLIC and not engaged <= observers:
            raise ChpmError("CHPM direct engagement needs an observable fragment.")
    return {actor: _actor(raw, available, actor) for actor in sorted(names)}


def _actor(raw: Projection, available: dict[str, str], actor: str) -> Perception:
    relevant = [key for key in available if actor in raw.fragments[key].observers]
    essential = [key for key in relevant if raw.fragments[key].kind != "incidental"]
    incidental = [key for key in relevant if raw.fragments[key].kind == "incidental"]
    kept = set(essential + incidental[:2])
    quotes = list(dict.fromkeys(available[key] for key in available if key in kept))
    if len("\n".join(quotes)) > MAX_OBSERVED_CHARS:
        raise ChpmError(
            "CHPM observable actions exceed their budget; no essential action was discarded."
        )
    return Perception(
        actor_id=actor,
        quotes=quotes,
        quote_kinds=[
            raw.fragments[
                next(key for key in available if key in kept and available[key] == quote)
            ].kind
            for quote in quotes
        ],
        uncertain=any(entry.kind == "uncertain" for entry in raw.fragments.values()),
        engaged=any(actor in entry.engaged for entry in raw.fragments.values()),
        coverage={
            key: (
                "incidental_budget"
                if key in incidental and key not in kept
                else "not_observed"
                if entry.kind in PUBLIC and actor not in entry.observers
                else entry.kind
            )
            for key, entry in raw.fragments.items()
        },
        observed_kinds={key: raw.fragments[key].kind for key in available if key in kept},
    )
