"""Group source-ordered changes to one existing possession without guessing events."""

from collections.abc import Sequence

from backend.engine.narrated_items.participants import resolve_participants
from backend.engine.narrated_items.schema import ItemAction
from backend.engine.visual_novel.continuity import Possessions


def batches(
    actions: list, source_indices: Sequence[int] | None
) -> list[list[tuple[int, ItemAction]]]:
    indices = tuple(range(len(actions))) if source_indices is None else tuple(source_indices)
    if (
        len(indices) != len(actions)
        or len(set(indices)) != len(indices)
        or any(type(index) is not int or not 0 <= index <= 5 for index in indices)
    ):
        raise ValueError("Invalid item action source indices.")
    groups: dict[tuple, list] = {}
    for index, action in zip(indices, actions, strict=True):
        key = ("existing", action.item_id) if action.item_id else ("new", index)
        groups.setdefault(key, []).append((index, action))
    return list(groups.values())


def prepare(
    entries: list[tuple[int, ItemAction]], actors: dict, narration: str
) -> list[ItemAction]:
    actions = [resolve_participants(action, actors) for _, action in entries]
    if len(actions) == 1:
        return actions
    end = -1
    owner = actions[0].source_owner
    for action in actions:
        start = narration.find(action.evidence)
        if (
            action.basis != "completed"
            or action.source_owner != owner
            or start < end
            or narration.count(action.evidence) != 1
        ):
            raise ValueError(
                "Item chain needs completed actions, continuous ownership and unambiguous narrative order."
            )
        end = start + len(action.evidence)
        owner = action.destination_owner
    return actions


def already_applied(actions: list[ItemAction], snapshot: Possessions) -> bool:
    """Do not undo intermediate clothing states after mechanics applied the final transfer."""
    return (
        len(actions) > 1
        and actions[0].item_id in snapshot.items
        and snapshot.owners.get(actions[0].item_id or "") == actions[-1].destination_owner
        and actions[0].source_owner != actions[-1].destination_owner
    )
