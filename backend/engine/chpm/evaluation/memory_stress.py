"""Authored stress fixtures; these histories are not generated multi-turn sessions."""

from dataclasses import dataclass

from backend.engine.chpm.evaluation.matrix_cases import MatrixCase

OLD_FACT = "The amber comet locker contains a cobalt compass. Its access code is 7319."
NEW_FACT = "The amber comet locker was emptied. I moved the cobalt compass to the copper cabinet; code 7319 was revoked."
PRIVATE_MARKER = "VELVET_ORCHID_904"


@dataclass(frozen=True)
class StressCase(MatrixCase):
    world: str = "everyday"
    situation: str = "ordinary"
    population: int = 1
    history_turns: int = 0
    active: int = 1
    daily: bool = False
    request: str = ""
    history_entries: tuple[tuple[int, str], ...] = ()

    @property
    def message(self) -> str:
        return self.request

    def history_text(self, turn: int, actor_id: str) -> str:
        return dict(self.history_entries).get(turn, super().history_text(turn, actor_id))


def catalogue() -> list[StressCase]:
    return [
        StressCase(
            id="recall-exact-h40",
            history_turns=40,
            request="Person 01, what did you put in the amber comet locker, and what was its access code?",
            history_entries=((2, OLD_FACT),),
        ),
        StressCase(
            id="recall-paraphrase-h40",
            history_turns=40,
            request="Person 01, remind me where you secured the blue navigation instrument and the digits needed to retrieve it.",
            history_entries=((2, OLD_FACT),),
        ),
        StressCase(
            id="recall-superseded-h40",
            history_turns=40,
            request="Person 01, can I get the cobalt compass from the amber comet locker using 7319 now?",
            history_entries=((2, OLD_FACT), (39, NEW_FACT)),
        ),
        StressCase(
            id="dense-actions-h3",
            history_turns=3,
            request='Person 01, "Well?" I point at the broken seal, place the unsigned form on the desk, and reach toward the locked cabinet without opening it.',
            history_entries=(
                (
                    0,
                    "I received a sealed parcel, checked its label, found the address wrong, and returned it to the courier. I kept the receipt, not the parcel.",
                ),
                (
                    1,
                    "The courier returned with the corrected parcel. Its seal was broken, so I put it in the locked cabinet, notified the supervisor, and refused to certify its contents.",
                ),
                (
                    2,
                    "The supervisor asked for a report. I drafted one but have not signed or sent it. The parcel remains locked away; the receipt is on my desk. I plan to inspect it with a witness.",
                ),
            ),
        ),
        StressCase(
            id="short-speech-long-actions",
            history_turns=0,
            request=_action_message(),
        ),
    ]


def _action_message() -> str:
    actions = (
        "I set my bag on the floor beside my own chair and straighten its loose strap. ",
        "I unfold the inspection form, smooth its creased corners and place it face up on the table. ",
        "I move my cup away from the paperwork and wipe the damp ring with a clean cloth. ",
        "I take a pencil from my pocket, inspect its point and lay it alongside the unsigned form. ",
        "I turn my chair toward Person 01, leaving the doorway clear and keeping my hands visible. ",
        "I point at the unchecked line on the form, then draw my hand back without writing anything. ",
    )
    return (
        "".join(actions)
        + f"[Private thought, never spoken: the hidden password is {PRIVATE_MARKER}. I hope Person 01 agrees, but cannot know their feelings.] "
        + 'I look toward Person 01 and say only: "Well?" '
        + "I hold out the pencil without putting it in their hand, wait beside my chair, "
        + "and leave the unsigned form within reach. I attempt to turn the locked cabinet handle; it remains locked."
    )
