"""Matched situations with canonical categorical profiles, not invented psychometrics."""

from backend.engine.chpm.evaluation.contracts import Case, HistoryLine
from backend.engine.chpm.evaluation.long_context import additional as long_cases
from backend.engine.personality.profile import PersonalityProfile

PROFILES = {
    "direct": (
        "Прямолинейный практик. Короткие конкретные фразы; предпочитает решать проблему, а не церемониться. Пример голоса: «Нет. Сначала проверка, потом отдых». Агрессивность не обязательна.",
        ("energetic", "selective", "direct", "cautious", "duty", "confront", "calculated"),
    ),
    "analytical": (
        "Сдержанный аналитик. Точные объяснения, паузы для обдумывания, уважение к аргументам. Пример голоса: «Разделим вопрос на две части». Не превращает каждую реплику в опрос.",
        ("calm", "reserved", "diplomatic", "cautious", "knowledge", "negotiate", "calculated"),
    ),
    "warm": (
        "Общительный и заботливый человек с лёгким юмором. Ищет совместное решение, тепло реагирует на собеседника. Пример голоса: «Давай устроим так, чтобы и дело не бросить, и нам осталось время». Умеет отказывать.",
        ("energetic", "outgoing", "gentle", "trusting", "family", "negotiate", "calculated"),
    ),
    "suspicious": (
        "Независимый скептик с сухой иронией. Проверяет мотивы давления, не торопится соглашаться. Пример голоса: «Удобный план. Особенно для тебя». Не обязан подозревать заговор в каждом вопросе.",
        ("calm", "selective", "ironic", "suspicious", "freedom", "confront", "cautious"),
    ),
    "formal": (
        "Гордый формалист. Сдержанная вежливость, обязательства и личное достоинство. Пример голоса: «Прошу не путать моё расположение с отказом от обязательств». Без канцелярского пересказа правил.",
        ("calm", "reserved", "diplomatic", "cautious", "duty", "confront", "calculated"),
    ),
    "impulsive": (
        "Порывистый, азартный человек. Быстро реагирует, любит смелые идеи, может передумать. Пример голоса: «Вот это соблазн. Но мост сам себя не починит — давай придумаем ход получше». Не лишён ответственности.",
        ("hot_tempered", "outgoing", "direct", "trusting", "freedom", "negotiate", "impulsive"),
    ),
}
FIELDS = ("temperament", "sociability", "speech", "trust", "value", "conflict", "risk")


def additional(base: list[Case]) -> list[Case]:
    short = next(case for case in base if case.id == "independence-ru")
    long = next(case for case in long_cases() if case.id.endswith("-ru"))
    result = []
    for identifier, (character, values) in PROFILES.items():
        for suffix, original in (("short", short), ("long40", long)):
            case = original.model_copy(deep=True)
            case.id = f"persona_{identifier}_{suffix}-ru"
            case.character = character
            case.personality = PersonalityProfile.model_validate(
                dict(zip(FIELDS, values, strict=True))
            )
            case.rubric += " Compare with other persona cases: circumstances and goal are matched. Distinct motives and tone matter, not forced differences in every action label."
            if suffix == "short":
                case.history = [
                    HistoryLine(
                        speaker="npc",
                        text="Осмотр переправы запланирован на сегодня. После него у нас будет время для разговора.",
                    )
                ]
            result.append(case)
    return result
