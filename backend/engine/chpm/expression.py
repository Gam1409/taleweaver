"""Validate expression coverage without turning a performed action into speech."""

from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import Decision, Verdict


def validate(decisions: dict[str, Decision], verdict: Verdict, text: str) -> None:
    speech = {entry.actor_id: entry for entry in verdict.evidence}
    actions = {entry.actor_id: entry for entry in verdict.actions}
    if (
        len(speech) != len(verdict.evidence)
        or len(actions) != len(verdict.actions)
        or speech.keys() | actions.keys() != decisions.keys()
    ):
        raise ChpmError(
            "CHPM validator did not identify every controlled NPC exactly once per expression type."
        )
    for action in verdict.actions:
        if not action.quote or action.quote not in text:
            raise ChpmError("CHPM validator supplied no exact action evidence.")
    for entry in verdict.evidence:
        # An empty speech placeholder adds no attribution to an independently valid action.
        silent = not entry.quote and (
            decisions[entry.actor_id].selected.kind == "DEFER" or entry.actor_id in actions
        )
        if not silent and (not entry.quote or entry.quote not in text):
            raise ChpmError("CHPM validator supplied no exact speech evidence.")
