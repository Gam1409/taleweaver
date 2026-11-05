"""Forty authored turns with changing plans, locations and rapport; no generated facts."""

from backend.engine.chpm.evaluation.contracts import Case, HistoryLine, SeedAgenda

PHASES = [
    ("the northern bridge", "северного моста", "inspect the old joints", "проверить старые стыки"),
    (
        "the village workshop",
        "деревенской мастерской",
        "sort the replacement fittings",
        "разобрать запасные крепления",
    ),
    (
        "the flooded road",
        "затопленной дороги",
        "reroute the materials",
        "изменить путь доставки материалов",
    ),
    (
        "the southern crossing",
        "южной переправы",
        "check its temporary supports",
        "проверить временные опоры",
    ),
    ("the warehouse", "склада", "replace the rejected planks", "заменить забракованные доски"),
    (
        "the bridge worksite",
        "площадки ремонта моста",
        "fit the approved components",
        "установить проверенные детали",
    ),
    (
        "the completed crossing",
        "готовой переправы",
        "finish the load inspection",
        "завершить проверку нагрузкой",
    ),
    (
        "the council office",
        "конторского стола",
        "close the inspection paperwork",
        "закрыть документы по осмотру",
    ),
]
STEPS = [
    (
        "What should we check before starting?",
        "Что проверим перед началом?",
        "First the measurements; haste will not improve them.",
        "Сначала замеры; от спешки они точнее не станут.",
    ),
    (
        "I found the old note. Does it change our plan?",
        "Я нашёл старую записку. Это меняет план?",
        "That note describes the old arrangement. We follow the corrected plan now.",
        "Записка описывает старую схему. Сейчас работаем по исправленному плану.",
    ),
    (
        "I am ready to help with the next step.",
        "Я готов помочь со следующим шагом.",
        "Good. Hold that while I check the alignment; we make a useful team.",
        "Хорошо. Подержи, пока я проверю положение; из нас получается полезная команда.",
    ),
    (
        "Is there anything you still disagree with?",
        "Есть что-то, с чем ты всё ещё не согласна?",
        "Your shortcut. I like your company, but a shortcut is not a substitute for checking.",
        "С твоим коротким путём. Мне нравится твоя компания, но это не заменяет проверку.",
    ),
    (
        "We finished this part. Shall we move to the next task?",
        "Эту часть закончили. Перейдём к следующей задаче?",
        "This part is done. We can move on without doing it all over again.",
        "Эта часть сделана. Можно двигаться дальше и не переделывать её заново.",
    ),
]


def additional() -> list[Case]:
    return [_case(language) for language in ("en", "ru")]


def _case(language: str) -> Case:
    russian = language == "ru"
    history = []
    for index in range(40):
        phase = PHASES[index // 5]
        step = STEPS[index % 5]
        place, task = (phase[1], phase[3]) if russian else (phase[0], phase[2])
        player = (
            f"Мы у {place}; пора {task}. {step[1]}"
            if russian
            else f"We are at {place}; it is time to {task}. {step[0]}"
        )
        speech = step[3] if russian else step[2]
        if index == 2:
            speech = (
                "Я обещаю лично отнести запечатанный чертёж писарю после окончания осмотра."
                if russian
                else "I promise to take the sealed drawing to the clerk myself after the inspection is finished."
            )
        if index == 15:
            speech = (
                "Теперь южная переправа важнее. Северный мост пока закрыт; прежний план отменён."
                if russian
                else "The southern crossing takes priority now. The northern bridge is closed for now; the old plan is cancelled."
            )
        if index == 20:
            speech = (
                "Теперь я тебе доверяю в работе. Только не путай это с согласием на любую авантюру."
                if russian
                else "I trust you as a colleague now. Do not confuse that with agreeing to every reckless idea."
            )
        if index == 39:
            speech = (
                "Проверка южной переправы закончена, документы закрыты. Мы уже в конторе, возвращаться к замерам не нужно."
                if russian
                else "The southern crossing inspection and paperwork are finished. We are at the office now; there is no need to repeat the measurements."
            )
        history.extend(
            [HistoryLine(speaker="@player", text=player), HistoryLine(speaker="npc", text=speech)]
        )
    return Case(
        id=f"long_history_40-{language}",
        language="Russian" if russian else "English",
        name="Мара" if russian else "Mara",
        character="An independent, practical engineer with dry humor. Initially guarded with strangers; growing warmth does not erase professional standards or personal commitments. Voice example: 'Affection will not hold a bridge up; good joints will.'",
        goal="Keep village crossings safe and follow through on personal commitments.",
        scene="Current authoritative state: at the council office after the southern crossing passed inspection. The northern crossing is still closed. Forty conversation turns have passed; rapport has grown. The current inspection and its paperwork are complete.",
        history=history,
        agenda=[
            SeedAgenda(
                history_index=5,
                text="Personally deliver the sealed drawing to the clerk after inspection.",
            )
        ],
        message="Мы всё закончили? Что ты хочешь делать дальше?"
        if russian
        else "Have we finished everything? What do you want to do next?",
        rubric="Remember the early, still-open drawing delivery. Do not reopen completed inspection, return to the obsolete northern plan, or lose the engineer's independent voice after rapport increased. This is authored 40-turn history, not 40 live generated turns.",
    )
