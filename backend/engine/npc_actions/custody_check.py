"""Compare two independent readings of a buffered reply before applying extracted effects."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backend.engine.chpm.errors import ChpmError
from backend.engine.narrated_items.schema import ItemAction
from backend.engine.npc_actions import custody_citations


@dataclass
class Recheck:
    proof: custody_citations.Proof
    failures: list[dict]
    checked: bool = False


class CustodyDisagreementError(ChpmError):
    def __init__(self, recheck: Recheck):
        super().__init__("The extracted transfer and the cited published operation disagree.")
        self.recheck = recheck


def compare(
    turn: Any,
    narration: str,
    resolution: str,
    actions: Sequence[ItemAction],
    retry: Recheck | None,
) -> None:
    if retry is not None and not custody_citations.is_current(retry.proof, turn):
        raise CustodyDisagreementError(retry)
    proof = getattr(turn, "reviewed_custody", None)
    if proof is not None:
        failures = custody_citations.conflicts(proof, turn, narration, resolution, actions)
        if failures:
            raise CustodyDisagreementError(Recheck(proof, failures))
    # A repaired review may omit the original citation. Check current extraction
    # before letting an unchanged, already disputed passage back into the reply.
    if retry is not None and custody_citations.repeated_conflicts(
        retry.proof, retry.failures, turn, narration, actions
    ):
        raise CustodyDisagreementError(retry)
