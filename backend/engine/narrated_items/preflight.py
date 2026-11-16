"""Explain skipped item checks without relaxing rules or changing source budgets."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SkippedCheck:
    reason_code: str
    reason: str
    narration_characters: int
    narration_limit: int

    def details(self) -> dict:
        return asdict(self)

    def message(self) -> str:
        return (
            f"Item reconciliation needs review: {self.reason} "
            "No additional inventory changes were applied."
        )


def skipped_check(
    narration: str, *, blocked: bool, blocked_reason: str, limit: int
) -> SkippedCheck | None:
    characters = len(narration)
    if blocked:
        return SkippedCheck(
            "rules_rejected",
            blocked_reason or "An earlier rules check rejected the proposed action.",
            characters,
            limit,
        )
    if characters > limit:
        return SkippedCheck(
            "narration_limit",
            f"The completed narration contains {characters} characters; this check's limit is {limit}.",
            characters,
            limit,
        )
    return None
