"""Conservative classification for recovery; body coverage alone is not underwear."""

import re

from backend.engine.clothing.schema import Garment
from backend.engine.narrated_items.errors import ItemFailure
from backend.engine.narrated_items.schema import ItemAction

# Whole item names only: description/evidence can mention underwear beneath an ordinary skirt.
# This supplements the explicit flag, never clears it. It is not an exhaustive language classifier.
_INNER_NAME = re.compile(
    r"\b(?:underwear|underpants|panties|briefs|thongs?|bras?|brassieres?|boxers|lingerie|"
    r"garter belt|suspender belt|трусы|трусики|трусиков|стринги|стрингов|лифчик\w*|"
    r"бюстгальтер\w*|нижнее бель[её]|пояс для чулок)\b",
    re.IGNORECASE,
)


def classify_action(action: ItemAction) -> ItemAction:
    proposal = action.new_item
    if proposal is None or proposal.clothing is None or not _INNER_NAME.search(proposal.name):
        return action
    garment = classify_garment(proposal.name, proposal.clothing)
    corrected = proposal.model_copy(update={"clothing": garment})
    return action.model_copy(update={"new_item": corrected})


def classify_garment(name: str, garment: Garment) -> Garment:
    """Supplement the explicit flag; ordinary coverage alone never implies underwear."""
    return garment.model_copy(update={"underwear": True}) if _INNER_NAME.search(name) else garment


def partition_rejections(
    rejected: list[ItemFailure], *, detailed: bool, age: object
) -> tuple[list[str], list[str]]:
    reasons = []
    if not detailed:
        reasons.append("Clothing layer tracking is disabled in this session")
    if type(age) is not int:
        reasons.append("NPC age is not recorded as an integer")
    elif age < 18:
        reasons.append(f"NPC age is {age}; inner clothing requires an adult owner")
    skipped = []
    errors = []
    for failure in rejected:
        if failure.code in {"inner_creation_policy", "inner_wear_policy"}:
            skipped.append(
                f"{failure.label}: " + "; ".join(reasons) + "." if reasons else failure.message()
            )
        else:
            errors.append(failure.message())
    return errors, skipped
