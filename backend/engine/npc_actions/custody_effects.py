"""Compare transfer and wardrobe dimensions without treating either as the other's owner."""

from dataclasses import dataclass
from typing import Any

from backend.engine.actor_aliases import canonical_owner
from backend.engine.narrated_items.schema import ItemAction


@dataclass(frozen=True)
class Reading:
    item_id: str | None
    source_owner: str
    destination_owner: str
    disposition: str
    uncovered_regions: tuple[str, ...] | None
    attachment_slot: str | None

    @property
    def direction(self) -> tuple[str, str]:
        return self.source_owner, self.destination_owner


def read(action: ItemAction) -> Reading:
    return Reading(
        action.item_id,
        canonical_owner(action.source_owner),
        canonical_owner(action.destination_owner),
        action.disposition,
        tuple(sorted(action.uncovered_regions)) if action.uncovered_regions is not None else None,
        action.attachment_slot,
    )


def wardrobe_echo(action: Any, effect: dict, *, wearer: str | None = None) -> bool:
    owner = wearer or action.source_owner
    if (
        canonical_owner(effect["actor_id"]) != owner
        or (wearer is None and action.source_owner != action.destination_owner)
        or effect.get("item_id") != action.item_id
        or action.attachment_slot is not None
    ):
        return False
    if effect.get("operation") == "remove":
        return action.disposition in {"carried", "held"}
    return (
        effect.get("operation") in {"wear", "adjust"}
        and action.disposition == "worn"
        and (
            action.uncovered_regions is None
            or set(action.uncovered_regions) == set(effect.get("uncovered_regions") or ())
        )
    )


def transfer_echo(action: Reading, effect: dict, effects: list[dict]) -> bool:
    source, destination = effect.get("source_owner"), effect.get("destination_owner")
    if (
        effect.get("item_id") != action.item_id
        or not isinstance(source, str)
        or not isinstance(destination, str)
        or canonical_owner(source) != action.source_owner
        or canonical_owner(destination) != action.destination_owner
    ):
        return False
    if action.disposition == "worn":
        start = effect.get("_publication_index", -1)
        end = min(
            (
                other["_publication_index"]
                for other in effects
                if other.get("item_id") == action.item_id
                and "destination_owner" in other
                and other.get("_publication_index", -1) > start
            ),
            default=None,
        )
        return any(
            other.get("_publication_index", -1) > start
            and (end is None or other.get("_publication_index", -1) < end)
            and wardrobe_echo(action, other, wearer=action.destination_owner)
            for other in effects
        )
    return (
        effect.get("disposition", "carried") in {"carried", "held"}
        and action.disposition in {"carried", "held"}
        and action.uncovered_regions is None
        and action.attachment_slot is None
    )


def echo(action: ItemAction, effects: list[dict]) -> bool:
    reading = read(action)
    return any(
        transfer_echo(reading, effect, effects) or wardrobe_echo(reading, effect)
        for effect in effects
    )
