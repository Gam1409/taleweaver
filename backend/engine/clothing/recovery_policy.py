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


def partition_rejections(
    rejected: list[str], *, detailed: bool, age: object
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
    for error in rejected:
        suffix = next((text for text in POLICY_REJECTIONS if error.endswith(text)), None)
        if suffix:
            skipped.append(error[: -len(suffix)] + "; ".join(reasons) + "." if reasons else error)
        else:
            errors.append(error)
    return errors, skipped
