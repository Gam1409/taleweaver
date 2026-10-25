"""Localized memory notifications without translating stored engine values."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from backend.core.content_language import default_language
from backend.models.game_session import GameSession


@dataclass(frozen=True)
class MemoryLabels:
    saved: str
    local: str
    global_: str
    positive: str
    negative: str
    neutral: str


_LABELS = {
    "English": MemoryLabels(
        "Memory saved", "scene-local", "global", "positive", "negative", "neutral"
    ),
    "German": MemoryLabels(
        "Erinnerung gespeichert", "szenen-lokal", "global", "positiv", "negativ", "neutral"
    ),
    "French": MemoryLabels(
        "Souvenir enregistré", "scène actuelle", "global", "positif", "négatif", "neutre"
    ),
    "Spanish": MemoryLabels(
        "Recuerdo guardado", "escena actual", "global", "positivo", "negativo", "neutral"
    ),
    "Italian": MemoryLabels(
        "Ricordo salvato", "scena attuale", "globale", "positivo", "negativo", "neutro"
    ),
    "Portuguese": MemoryLabels(
        "Memória salva", "cena atual", "global", "positiva", "negativa", "neutra"
    ),
    "Russian": MemoryLabels(
        "Воспоминание сохранено",
        "текущая сцена",
        "весь мир",
        "положительное",
        "отрицательное",
        "нейтральное",
    ),
    "Japanese": MemoryLabels(
        "記憶を保存しました", "現在のシーン", "全体", "肯定的", "否定的", "中立"
    ),
    "Chinese": MemoryLabels("记忆已保存", "当前场景", "全局", "积极", "消极", "中性"),
}


async def notification_language(manager: Any) -> str:
    """Use the turn override or persisted session choice without ORM lazy loading."""
    requested = getattr(manager, "turn_language", None)
    if requested:
        return default_language(requested)
    saved = await manager.db.scalar(
        select(GameSession.content_language).where(GameSession.id == manager.state.session_id)
    )
    return default_language(
        saved,
        getattr(manager.user, "default_language", None),
        getattr(manager.adventure, "language", None),
    )


def memory_saved_message(description: str, scope: str, emotion: str, language: str) -> str:
    """Localize only notification labels; preserve the fact text and canonical JSON."""
    labels = _LABELS[default_language(language)]
    scope_label = labels.local if scope == "local" else labels.global_
    emotion_label = {
        "positive": labels.positive,
        "negative": labels.negative,
    }.get(emotion, labels.neutral)
    return f"{labels.saved} ({scope_label}, {emotion_label}): {description}"
