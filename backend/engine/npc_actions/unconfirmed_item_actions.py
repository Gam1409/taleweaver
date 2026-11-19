"""Check typed completions that have no matching public command in a two-phase turn."""

from collections.abc import Sequence

from backend.engine.actor_aliases import canonical_owner, public_actor_id
from backend.engine.narrated_items.schema import ItemAction
from backend.engine.npc_actions import custody_effects
from backend.engine.visual_novel.continuity import SCENE


def _contradicts(action: ItemAction, item: dict) -> bool:
    owner = item.get("owner_id")
    if not isinstance(owner, str):
        return False
    if canonical_owner(owner) != canonical_owner(action.destination_owner):
        return True
    wear = item.get("wear_status")
    return wear in {"worn", "not_worn"} and (wear == "worn") != (action.disposition == "worn")


def conflicts(
    actions: Sequence[ItemAction],
    narration: str,
    occurrences: tuple[tuple[str, int, int, str, bool], ...],
    controlled: set[str],
    entities: dict[str, dict],
    effects: list[dict],
) -> list[dict]:
    issues = []
    for action in actions:
        # The carrier of a received gift did not necessarily initiate it. Leave an
        # independent donor's acts to their own state owner and evidence checks.
        performer = public_actor_id(action.performed_by) if action.performed_by else None
        known_performer = (
            performer if entities.get(performer or "", {}).get("kind") == "actor" else None
        )
        actor = known_performer or (
            action.destination_owner if action.source_owner == SCENE else action.source_owner
        )
        if actor not in controlled or action.basis != "completed" or not action.item_id:
            continue
        item = entities.get(action.item_id, {})
        span = action.evidence_span
        if (
            item.get("kind") != "item"
            or span is None
            or not span.matches(narration, action.evidence)
        ):
            continue
        # An unresolved performer cannot borrow another actor's receipt, even
        # when the item already happens to be at the narrated endpoint.
        if performer == known_performer and custody_effects.echo(
            action, effects, performer=performer
        ):
            continue
        # A known endpoint can refute an unattributed inference. It cannot prove
        # that a named performer actually completed an unrecorded transition.
        if performer is None and not _contradicts(action, item):
            continue
        passage = next(
            (key for key, start, end, *_ in occurrences if start <= span.start and span.end <= end),
            None,
        )
        if passage is not None:
            issues.append(
                {
                    "reason_code": "unconfirmed_item_change",
                    "actor_id": actor,
                    "passage_id": passage,
                    "claimed_target_id": action.item_id,
                }
            )
    return issues


def omitted_on_recheck(
    issues: Sequence[dict],
    original: tuple[tuple[str, int, int, str, bool], ...],
    revised: dict[str, list[tuple[str, int, int]]],
    actions: Sequence[ItemAction],
    narration: str,
) -> list[dict]:
    """An already disputed passage needs a fresh reading if its text survives repair."""
    hashes = {key: digest for key, _, _, digest, unique in original if unique}
    readings = [
        (action.item_id, span.start, span.end)
        for action in actions
        if (span := action.evidence_span) is not None and span.matches(narration, action.evidence)
    ]
    missing = []
    for issue in issues:
        if issue.get("reason_code") != "unconfirmed_item_change":
            continue
        matches = revised.get(hashes.get(issue["passage_id"], ""), [])
        if len(matches) != 1:
            continue
        key, start, end = matches[0]
        if not any(
            item == issue["claimed_target_id"] and start <= a and b <= end
            for item, a, b in readings
        ):
            missing.append({**issue, "passage_id": key})
    return missing
