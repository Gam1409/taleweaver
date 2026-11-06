"""Conservative classification for recovery; body coverage alone is not underwear."""

from backend.engine.clothing.classification import classify_action, classify_garment
from backend.engine.narrated_items.errors import ItemFailure

__all__ = ["classify_action", "classify_garment", "partition_rejections"]


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
