"""Player-facing NPC movement outcomes, without engine IDs or invented motives."""

from backend.core.content_language import default_language

_MESSAGES = {
    "English": ("{name} stays here.", "{name} cannot go to that location and stays here."),
    "Russian": (
        "{name} остаётся здесь.",
        "{name} не может перейти в эту локацию и остаётся на месте.",
    ),
    "German": ("{name} bleibt hier.", "{name} kann diesen Ort nicht betreten und bleibt hier."),
    "French": ("{name} reste ici.", "{name} ne peut pas se rendre à cet endroit et reste ici."),
    "Spanish": ("{name} se queda aquí.", "{name} no puede ir a ese lugar y se queda aquí."),
    "Italian": ("{name} rimane qui.", "{name} non può raggiungere quel luogo e rimane qui."),
    "Japanese": (
        "{name}はここに残ります。",
        "{name}はその場所へ移動できないため、ここに残ります。",
    ),
    "Chinese": ("{name}留在这里。", "{name}无法前往那个地点，因此留在这里。"),
    "Traditional Chinese": ("{name}留在這裡。", "{name}無法前往那個地點，因此留在這裡。"),
    "Arabic": ("{name}: البقاء هنا.", "{name}: تعذر الانتقال إلى ذلك المكان، والبقاء هنا."),
    "Korean": ("{name}: 여기에 머뭅니다.", "{name}: 그 장소로 이동할 수 없어 여기에 머뭅니다."),
    "Portuguese": ("{name} fica aqui.", "{name} não pode ir a esse local e fica aqui."),
}


def movement_message(name: str, restricted: bool, language: str | None) -> str:
    return _MESSAGES[default_language(language)][int(restricted)].format(name=name)


_ARRIVALS = {
    "English": "{name} moved to {place}.",
    "Russian": "{name} перемещается в локацию «{place}».",
    "German": "{name} geht nach {place}.",
    "French": "{name} se rend à {place}.",
    "Spanish": "{name} se traslada a {place}.",
    "Italian": "{name} si sposta in {place}.",
    "Japanese": "{name}は{place}へ移動しました。",
    "Chinese": "{name}移动到了{place}。",
    "Traditional Chinese": "{name}移動到了{place}。",
    "Arabic": "{name}: الانتقال إلى {place}.",
    "Korean": "{name}: 이동한 장소 — {place}.",
    "Portuguese": "{name} vai para {place}.",
}


def movement_arrival(name: str, place: str, language: str | None) -> str:
    return _ARRIVALS[default_language(language)].format(name=name, place=place)
