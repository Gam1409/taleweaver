"""Shared garment-name classification for live registration and recovery."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from backend.engine.clothing.schema import Garment

if TYPE_CHECKING:
    from backend.engine.narrated_items.schema import ItemAction

# Whole item names only: description/evidence can mention underwear beneath an ordinary skirt.
# This supplements the explicit flag, never clears it. It is not an exhaustive language classifier.
_INNER_NAME = re.compile(
    r"\b(?:underwear|underpants|panties|briefs|thongs?|bras?|brassieres?|boxers|lingerie|"
    r"garter belt|suspender belt|трусы|трусики|трусиков|стринги|стрингов|лифчик\w*|"
    r"бюстгальтер\w*|нижнее бель[её]|пояс для чулок)\b",
    re.IGNORECASE,
)


def classify_garment(name: str, garment: Garment) -> Garment:
    """Supplement the explicit flag; body coverage alone never implies underwear."""
    return garment.model_copy(update={"underwear": True}) if _INNER_NAME.search(name) else garment


def classify_action(action: ItemAction) -> ItemAction:
    """Normalize at the apply boundary without changing the raw model proposal."""
    proposal = action.new_item
    if proposal is None or proposal.clothing is None:
        return action
    garment = classify_garment(proposal.name, proposal.clothing)
    corrected = proposal.model_copy(update={"clothing": garment})
    return action.model_copy(update={"new_item": corrected})
