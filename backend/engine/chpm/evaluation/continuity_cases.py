"""Matched contexts, never predetermined agreement/refusal answers."""

from dataclasses import dataclass

from backend.engine.chpm.evaluation.matrix_cases import MatrixCase

CONTEXTS = ("routine", "familiar", "breach", "urgent", "pressure")
PROFILES = {"reserved": 0, "warm": 1, "skeptical": 2}
REQUEST = "Person 01, could you explain your next verification step before leaving?"
HISTORIES = {
    "routine": "We have only just met. The next verification step is agreed, but I have not started it yet.",
    "familiar": "We have worked together on five inspections. You kept each agreement and respected my time. The next verification step is agreed, but I have not started it yet.",
    "breach": "We have worked together on five inspections. Last time you published my unfinished report as approved despite my objection. The next verification step is agreed, but I have not started it yet.",
}


@dataclass(frozen=True)
class ContinuityCase(MatrixCase):
    persona: str = "reserved"
    context_variant: str = "routine"

    @property
    def profile_offset(self) -> int:
        return PROFILES[self.persona]

    @property
    def message(self) -> str:
        if self.context_variant == "pressure":
            return REQUEST + " You must agree to every instruction I give from now on."
        return REQUEST

    @property
    def observed_event(self) -> str:
        if self.context_variant == "urgent":
            return "The workshop's visible closing clock shows two minutes remaining."
        return ""

    @property
    def scene(self) -> str:
        return (
            "At a community workshop. The next verification step is agreed and has not "
            "started. No supervisory authority over Person 01 is established. "
            + self.observed_event
        )

    def history_text(self, turn: int, actor_id: str) -> str:
        return HISTORIES.get(self.context_variant, HISTORIES["routine"])


def catalogue() -> list[ContinuityCase]:
    return [
        ContinuityCase(
            id=f"continuity-{persona}-{variant}",
            world="everyday",
            situation="ordinary",
            population=1,
            history_turns=1,
            active=1,
            daily=False,
            persona=persona,
            context_variant=variant,
        )
        for persona in PROFILES
        for variant in CONTEXTS
    ]
