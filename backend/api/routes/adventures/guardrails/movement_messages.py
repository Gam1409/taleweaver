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
    "Portuguese": ("{name} fica aqui.", "{name} não pode ir a esse local e fica aqui."),
}


def movement_message(name: str, restricted: bool, language: str | None) -> str:
    return _MESSAGES[default_language(language)][int(restricted)].format(name=name)
