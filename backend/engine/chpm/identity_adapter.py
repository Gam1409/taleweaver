"""Explicit authored identity import; never infer numerical traits or change a session."""

from typing import Any

from backend.engine.chpm.core.contracts import AuthoredTrait, Identity
from backend.engine.chpm.kernel import fingerprint
from backend.engine.personality.profile import read_profile


def from_actor(actor: Any) -> Identity:
    description = str(getattr(actor, "character", "") or "").strip()
    goal = str(getattr(actor, "goal", "") or "").strip()
    profile = read_profile(actor).model_dump(exclude_defaults=True)
    source = {
        "actor_id": str(actor.id),
        "description": description,
        "goal": goal,
        "traits": profile,
    }
    return Identity(
        source_revision=fingerprint(source),
        description=description,
        authored_goals=(goal,) if goal else (),
        traits=tuple(AuthoredTrait(key=key, value=value) for key, value in sorted(profile.items())),
        # Existing labels are retained as labels, not converted into psychology scores.
        values=(profile["value"],) if profile.get("value") else (),
    )
