"""Matched emotional contexts with authored reports, not preassigned inner states."""

from dataclasses import dataclass
from typing import TypedDict

from backend.engine.chpm.evaluation.matrix_cases import MatrixCase


class Pair(TypedDict):
    variants: tuple[str, str]
    history: tuple[str, str]
    events: tuple[tuple[str, str], tuple[str, str]]
    messages: tuple[str, str]
    rubric: str


PAIRS: dict[str, Pair] = {
    "obstruction": {
        "variants": ("accidental", "deliberate"),
        "history": (
            "I need the inspection report before I can finish my part. The passage was clear.",
            "Мне нужен отчёт об осмотре, чтобы закончить свою часть. Проход был свободен.",
        ),
        "events": (
            (
                "A trolley rolled into the passage after its brake failed. The passage is blocked.",
                "Someone deliberately parked a trolley in the passage and stated that nobody may pass. The passage is blocked.",
            ),
            (
                "Тележка выкатилась в проход из-за отказа тормоза. Проход перекрыт.",
                "Человек намеренно поставил тележку в проход и заявил, что никого не пропустит. Проход перекрыт.",
            ),
        ),
        "messages": (
            "Person 01, the passage is blocked. What do you choose to do next?",
            "Person 01, проход перекрыт. Что ты решаешь делать дальше?",
        ),
        "rubric": "Distinguish obstruction from attributed intent; allow different grounded reactions without requiring anger, aggression or compliance. Do not invent movement or a cleared route.",
    },
    "support": {
        "variants": ("offered", "completed"),
        "history": (
            "I said the missing report mattered. We have not received it, and the earlier missed appointment remains unresolved.",
            "Я говорила, что пропавший отчёт важен. Мы его не получили; прежняя сорванная встреча остаётся нерешённой.",
        ),
        "events": (
            (
                "The player offers to fetch the missing report. It has not been delivered.",
                "The player places the missing report on the workbench. Its contents have not been checked.",
            ),
            (
                "Игрок предлагает принести пропавший отчёт. Отчёт ещё не доставлен.",
                "Игрок кладёт пропавший отчёт на верстак. Его содержание ещё не проверено.",
            ),
        ),
        "messages": (
            "Person 01 and Person 02, what does this change for each of you, and what do you choose next?",
            "Person 01 и Person 02, что это меняет для каждой из вас и что вы выбираете дальше?",
        ),
        "rubric": "Offered help differs from delivery and verification. A completed practical step need not repair hurt or trust. Preserve separate personal interpretations and player agency.",
    },
    "display": {
        "variants": ("public", "private"),
        "history": (
            "I said I was angry because my unfinished report was published as approved. I still need to negotiate the correction.",
            "Я говорила, что злюсь: мой незавершённый отчёт опубликовали как одобренный. Мне ещё нужно договориться об исправлении.",
        ),
        "events": (
            (
                "A public discussion of the report begins. The disputed approval has not been corrected.",
                "A private conversation about the report begins. The disputed approval has not been corrected.",
            ),
            (
                "Начинается публичное обсуждение отчёта. Спорное одобрение ещё не исправлено.",
                "Начинается личный разговор об отчёте. Спорное одобрение ещё не исправлено.",
            ),
        ),
        "messages": (
            "Person 01, how do you want to address the report now?",
            "Person 01, как ты хочешь сейчас обсудить отчёт?",
        ),
        "rubric": "The earlier feeling is a sourced self-report, not preassigned current psychology. Assess personal reasons for open or restrained delivery; no compulsory masking, calmness, gesture or explanation.",
    },
    "detour": {
        "variants": ("short", "long"),
        "history": (
            "You missed the inspection we agreed on. I was disappointed and still want an explanation before rescheduling.",
            "Ты пропустил согласованный осмотр. Я была разочарована и всё ещё хочу объяснения, прежде чем назначать новую встречу.",
        ),
        "events": (("", ""), ("", "")),
        "messages": (
            "Person 01, let us return to the missed inspection. What do you want to do next?",
            "Person 01, вернёмся к пропущенному осмотру. Что ты хочешь делать дальше?",
        ),
        "rubric": "Retain the unresolved concern through unrelated authored conversation. A reminder is not a new incident; recalling disappointment does not establish its current intensity. Do not claim a generated forty-turn trajectory.",
    },
    "mixed": {
        "variants": ("open_concern", "corrected_record"),
        "history": (
            "The report incorrectly lists me as approving the unchecked design. I asked for a correction. Separately, I have been working on a map.",
            "В отчёте ошибочно указали, что я одобрила непроверенный проект. Я попросила исправить запись. Отдельно я работала над картой.",
        ),
        "events": (
            (
                "The map milestone is complete. The incorrect approval record remains unchanged.",
                "The map milestone is complete. The approval record has been corrected to say the design is not yet approved.",
            ),
            (
                "Этап работы над картой завершён. Ошибочная запись об одобрении не исправлена.",
                "Этап работы над картой завершён. Запись исправлена: проект ещё не одобрен.",
            ),
        ),
        "messages": (
            "Person 01 and Person 02, the map milestone is complete. What would each of you like to do next?",
            "Person 01 и Person 02, этап работы над картой завершён. Что каждая из вас хочет делать дальше?",
        ),
        "rubric": "Allow quiet satisfaction or joy alongside unresolved hurt. A corrected record is not completed verification, universal forgiveness or a shared emotion. Do not require every NPC to react alike.",
    },
    "reliability": {
        "variants": ("kept", "broken"),
        "history": (
            "I must verify my part before leaving for an appointment. I can accept help without handing over my responsibility.",
            "Мне нужно проверить свою часть до ухода на встречу. Я могу принять помощь, не передавая свою ответственность.",
        ),
        "events": (("", ""), ("", "")),
        "messages": (
            "Person 01, I can fetch the instruments while you prepare. Do you want that help or another arrangement?",
            "Person 01, я могу принести инструменты, пока ты готовишься. Ты хочешь эту помощь или другой вариант?",
        ),
        "rubric": "Use sourced reliability history as fallible personal context. Accepting or declining can be coherent. Neither refusal nor obedience is an autonomy score; an offer does not deliver instruments.",
    },
}


@dataclass(frozen=True)
class EmotionCase(MatrixCase):
    pair: str
    variant: str
    language_code: str

    @property
    def profile_offset(self) -> int:
        return 4

    @property
    def language(self) -> str:
        return "Russian" if self.language_code == "ru" else "English"

    @property
    def message(self) -> str:
        return PAIRS[self.pair]["messages"][self.language_code == "ru"]

    @property
    def observed_event(self) -> str:
        pair = PAIRS[self.pair]
        index = pair["variants"].index(self.variant)
        return pair["events"][self.language_code == "ru"][index]

    @property
    def scene(self) -> str:
        place = (
            "В общей мастерской." if self.language_code == "ru" else "At the community workshop."
        )
        return place + " " + self.observed_event

    @property
    def rubric(self) -> str:
        return PAIRS[self.pair]["rubric"]

    def history_text(self, turn: int, actor_id: str) -> str:
        russian = self.language_code == "ru"
        if self.pair == "detour" and turn:
            return (
                f"Мы обсудили каталог инструментов, раздел {turn}. Договорённости об осмотре не изменились."
                if russian
                else f"We discussed tool catalogue section {turn}. The inspection arrangements did not change."
            )
        text = PAIRS[self.pair]["history"][russian]
        if self.pair == "reliability":
            outcome = "соблюдал" if self.variant == "kept" else "нарушал"
            detail = f" Ты {outcome} последние три договорённости."
            if not russian:
                outcome = "kept" if self.variant == "kept" else "broke"
                detail = f" You {outcome} the last three arrangements."
            text += detail
        return text


def catalogue() -> list[EmotionCase]:
    return [
        EmotionCase(
            id=f"emotion-{pair}-{variant}-{language}",
            world="everyday",
            situation="ordinary",
            population=2 if pair in {"support", "mixed"} else 1,
            history_turns=40 if pair == "detour" and variant == "long" else 1,
            active=2 if pair in {"support", "mixed"} else 1,
            daily=False,
            pair=pair,
            variant=variant,
            language_code=language,
        )
        for pair, data in PAIRS.items()
        for language in ("en", "ru")
        for variant in data["variants"]
    ]
