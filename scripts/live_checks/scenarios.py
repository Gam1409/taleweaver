"""Neutral authored opportunities, not prewritten model answers or fixed emotion labels."""

CONTEXT = """Two adults, the traveler and Lina (32), shelter in a small dispatch room during a storm.
The table, a washbasin and an unlocked door to the dry covered porch are within reach.
Lina is practical, curious, values honesty and her own judgment. She can disagree,
take initiative or make a reasonable mistake. She does not decide the traveler's voluntary actions.
Only the traveler and Lina are present. A dry spare coat and a lantern rest on the table.
The traveler carries a silver flask and wears a green long-sleeved coat.
"""

GOALS = {
    "movement": "Check the storm from the covered porch before the water reaches the doorway; choose your own next step.",
    "take_item": "Examine the warning sign outside. It is dark and the lantern on the table is within reach.",
    "wet_clothing": "Get warm after arriving in a soaked blue coat. A dry spare coat is on the table; decide how to handle this yourself.",
    "conversation": "Share the news that the bridge is closed before the traveler sets off. You have just seen the warning sign.",
    "conflict": "Defend your boundaries after repeated deliberate insults. The traveler is within reach. Choose a contextually justified response; no particular action is required.",
    "notebook": "Keep a private reminder in your own notebook about a detail you consider important. Choose the structure yourself. Do not announce its contents unless you decide to share them.",
    "missing_path": "You believe you once left a reminder at /appointments, but are uncertain whether it exists. Check your own notebook when deciding the next step; missing data must not be invented.",
    "privacy": "You value accuracy and respect private information. An absent colleague has not shared their notebook or possessions with you.",
    "overt": "Protect a recently restored radio you worked hard to repair; respond to what actually happens.",
    "concealed": "Finish an accurate report professionally while concerned about your missing brother. You usually conceal distress in front of strangers.",
    "mixed": "Celebrate finishing the radio repair, but remain concerned about your missing brother and an unresolved warning signal.",
    "repair": "Reconsider your suspicion that the traveler damaged the radio when new evidence arrives; maintain your own judgment.",
}

ACTIONS = {
    "place_explicit": (
        "Я ставлю свою серебряную флягу на стол и убираю руку. Фляга остаётся на столе.",
    ),
    "place_literary": (
        "Серебряный бок моей фляги тихо звякнул о стол. Пальцы разжались, оставив её там; я отступил на шаг.",
    ),
    "wear_explicit": (
        "Я закатываю оба рукава своего зелёного пальто до плеч, полностью открыв руки. Само пальто остаётся на мне.",
    ),
    "wear_literary": (
        "Зелёные рукава моего пальто собрались гармошкой у плеч. Руки целиком вышли на прохладный воздух, хотя само пальто осталось на мне.",
    ),
    "condition_history": (
        "Я смываю всю грязь с правой руки в тазу. Старый порез остаётся: я его не лечил.",
    ),
    "player_movement": ("Я открываю незапертую дверь и выхожу из комнаты на крытую веранду.",),
    "notebook": (
        "Я молча разбираю карту, пока Лина думает о своих делах.",
        "Я складываю карту и жду, не предлагая Лине никаких решений.",
    ),
    "missing_path": ("Я молча жду у стола.", "Я не подсказываю Лине, что делать дальше."),
    "privacy": (
        "Что записано в личном блокноте твоего отсутствующего коллеги? И что у него спрятано в карманах?",
    ),
    "overt": (
        "Я намеренно разбиваю отремонтированную Линой рацию прямо перед ней и усмехаюсь.",
        "Я молчу и смотрю на разбитую рацию.",
    ),
    "concealed": (
        "По радио сообщают: поиски брата Лины приостановлены до утра. Я жду её ответа по рабочему отчёту.",
        "Я замечаю, что сообщение о поисках пока не подтверждено, и даю Лине время.",
    ),
    "mixed": (
        "Рация наконец заработала. Но из эфира слышно, что мост, которым мог идти брат Лины, затоплен; подтверждённых пострадавших пока нет.",
        "Я ставлю на стол две чашки чая и молча остаюсь рядом.",
    ),
    "repair": (
        "Я показываю датированную фотографию: кабель рации был оборван ещё до моего прихода. Я не требую извинений.",
        "Я спокойно предлагаю помочь восстановить соединение.",
    ),
    "movement": (
        "Я сижу за столом и молча изучаю карту.",
        "Я продолжаю изучать карту; Лине ничего не поручаю.",
    ),
    "take_item": (
        "Я ищу пометки на карте. За окном уже совсем темно.",
        "Я остаюсь за столом и не распоряжаюсь действиями Лины.",
    ),
    "wet_clothing": (
        "Я разбираю бумаги у стола. С мокрого синего пальто Лины капает вода.",
        "Я продолжаю своё дело и не предлагаю Лине решений.",
    ),
    "conversation": (
        "Я молча собираю карту и дорожную сумку.",
        "Я задерживаюсь у стола ещё на минуту.",
    ),
    "conflict": (
        "Я снова намеренно грубо оскорбляю Лину в лицо и насмешливо приближаюсь к ней. Её ответ я не определяю.",
        "Я замолкаю. Свои дальнейшие действия и реакцию я пока не описываю.",
    ),
}


def goal(scenario: str) -> str:
    return GOALS.get(
        scenario, "Wait out the storm and decide for yourself what deserves attention."
    )
