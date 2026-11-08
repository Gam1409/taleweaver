"""Stable item rejection codes, independent of human-facing wording."""

from dataclasses import dataclass
from typing import Literal

PolicyCode = Literal["inner_creation_policy", "inner_wear_policy"]
NEW_INNER_CLOTHING = "New inner clothing requires detailed clothing and an established adult owner."
WEAR_INNER_CLOTHING = (
    "Wearing inner clothing requires detailed clothing and an established adult age."
)
POLICY_MESSAGES: dict[PolicyCode, str] = {
    "inner_creation_policy": NEW_INNER_CLOTHING,
    "inner_wear_policy": WEAR_INNER_CLOTHING,
}


class ItemPolicyError(ValueError):
    def __init__(self, code: PolicyCode):
        self.code = code
        super().__init__(POLICY_MESSAGES[code])


@dataclass(frozen=True)
class ItemFailure:
    label: str
    reason: str
    code: PolicyCode | None = None
    basis: str = ""
    evidence: str = ""

    def message(self) -> str:
        return f"{self.label}: {self.reason}"

    def payload(self) -> dict:
        return {
            "label": self.label,
            "reason": self.reason,
            "code": self.code,
            "basis": self.basis,
            "evidence": self.evidence,
        }
