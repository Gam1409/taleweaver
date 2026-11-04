"""Conservative classification for recovery; body coverage alone is not underwear."""

import re

from backend.engine.narrated_items.schema import ItemAction

# Whole item names only: description/evidence can mention underwear beneath an ordinary skirt.
# This supplements the explicit flag, never clears it. It is not an exhaustive language classifier.
_INNER_NAME = re.compile(
    r"\b(?:underwear|underpants|panties|briefs|thongs?|bras?|brassieres?|boxers|lingerie|"
    r"garter belt|suspender belt|трусы|трусики|трусиков|стринги|стрингов|лифчик\w*|"
    r"бюстгальтер\w*|нижнее бель[её]|пояс для чулок)\b",
    re.IGNORECASE,
)
POLICY_REJECTIONS = (
    "New inner clothing requires detailed clothing and an established adult owner.",
    "Wearing inner clothing requires detailed clothing and an established adult age.",
)


def classify_action(action: ItemAction) -> ItemAction:
    proposal = action.new_item
    if proposal is None or proposal.clothing is None or not _INNER_NAME.search(proposal.name):
        return action
    garment = proposal.clothing.model_copy(update={"underwear": True})
    corrected = proposal.model_copy(update={"clothing": garment})
    return action.model_copy(update={"new_item": corrected})


def partition_rejections(rejected: list[str]) -> tuple[list[str], list[str]]:
    skipped = [error for error in rejected if error.endswith(POLICY_REJECTIONS)]
    errors = [error for error in rejected if not error.endswith(POLICY_REJECTIONS)]
    return errors, skipped
