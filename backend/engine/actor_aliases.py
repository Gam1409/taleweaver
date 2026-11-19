"""Public character references shared by observer views and operation projections."""

from backend.engine.visual_novel.continuity import PLAYER


def public_actor_id(identifier: str, *, player_id: str | None = None) -> str:
    """Use one player reference for canonical inventory and scene-staging identities."""
    return "@player" if identifier in {PLAYER, player_id} else identifier


def canonical_owner(identifier: str) -> str:
    """Resolve the public player reference only at a canonical ownership boundary."""
    return PLAYER if identifier == "@player" else identifier


def public_placement(placement: dict, *, player_id: str | None = None) -> dict:
    """Normalize only character targets; prop identifiers and descriptive text stay exact."""
    result = dict(placement)
    target = result.get("target")
    if result.get("target_kind") == "character" and isinstance(target, str):
        result["target"] = public_actor_id(target, player_id=player_id)
    return result
