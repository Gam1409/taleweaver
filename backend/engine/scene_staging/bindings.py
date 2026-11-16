"""Bind shared extraction aliases and accepted item actions to existing staging IDs."""

from copy import deepcopy

from backend.engine.visual_novel.continuity import PLAYER

from .schema import SceneExtraction


def actor_id(identifier: str, player_id: str) -> str:
    return player_id if identifier == PLAYER else identifier


def input_cast(cast: list[dict], previous: dict, player_id: str) -> tuple[list[dict], dict]:
    def alias(identifier: str) -> str:
        return PLAYER if identifier == player_id else identifier

    people = [{**person, "id": alias(person["id"])} for person in cast]
    projected = {}
    for identifier, raw in previous.items():
        row = deepcopy(raw)
        placement = row.get("placement") or {}
        if placement.get("target_kind") == "character":
            placement["target"] = alias(placement["target"])
        projected[alias(identifier)] = row
    return people, projected


def resolve(
    extraction: SceneExtraction, player_id: str, accepted: list[dict]
) -> tuple[SceneExtraction, int]:
    result = extraction.model_copy(deep=True)
    for change in result.changes:
        change.entity_id = actor_id(change.entity_id, player_id)
        if change.placement and change.placement.target_kind == "character":
            change.placement.target = actor_id(change.placement.target, player_id)
    for explicit in result.explicit:
        explicit.participants = [actor_id(value, player_id) for value in explicit.participants]
    approved = {entry["action_index"]: entry["item"]["id"] for entry in accepted}
    selected = []
    for prop in result.props:
        identifier = prop.item_id or approved.get(prop.item_action_index)
        if not identifier:
            continue
        selected.append(
            prop.model_copy(
                update={
                    "item_id": identifier,
                    "item_action_index": None,
                    "owner_id": actor_id(prop.owner_id, player_id),
                }
            )
        )
    rejected = len(result.props) - len(selected)
    result.props = selected
    return result, rejected
