"""Capture presentation from the same narrator call, never from rejected prose."""

import json
from typing import Any

from pydantic import ValidationError

from backend.core.engine_detailed_trace import sync_step
from backend.core.npc_presentation import (
    EMOTIONS,
    MAX_NPCS,
    MAX_THOUGHT,
    Cue,
    PortraitPreferences,
    source_hash,
)
from backend.engine.npc_presence import presence
from backend.engine.npc_presentation.diagnostics import report
from backend.engine.npc_presentation.settings import effective
from backend.engine.npc_presentation.stream import CLOSE, OPEN, FooterStream


def _catalog(manager: Any, entities: list[Any]) -> dict[str, str]:
    result = {}
    state = manager.state
    for entity in entities:
        override = (state.entity_states or {}).get(entity.id) or {}
        if entity.entity_type != "NPC" or override.get("is_hidden", entity.is_hidden):
            continue
        if override.get("current_scene_id", entity.current_scene_id) != state.current_scene_id:
            continue
        if presence(entity, state) != "absent":
            result[entity.id] = entity.name
    return result


class PresentationTurn:
    def __init__(self, preferences: PortraitPreferences, catalog: dict[str, str]) -> None:
        self.preferences = preferences
        self.catalog = catalog
        self.stream = FooterStream()
        self.body = ""
        self.output_chars = 0
        self.candidates: dict[str, dict] = {}
        self.outcomes: dict[str, str] = {}
        self.deferred_actor_ids: set[str] = set()

    @property
    def reminder(self) -> str:
        if not self.preferences.enabled or not self.catalog:
            return ""
        keys = ["npc_id"]
        if self.preferences.emotion_palette:
            keys.extend(("emotion", "intensity"))
        if self.preferences.character_thoughts:
            keys.append("thought")
        return (
            "PORTRAIT OUTPUT: After the visible story append the private footer "
            + OPEN
            + '{"npcs":[...]}'
            + CLOSE
            + ". Use JSON keys "
            + ", ".join(keys)
            + " and schema-defined enum identifiers in English exactly as specified. "
            "Natural-language values follow the story language. Use exact IDs from the supplied "
            "cast. Prose-only formatting applies to the visible story, not this private footer."
        )

    @property
    def prompt(self) -> str:
        if not self.preferences.enabled or not self.catalog:
            return ""
        fields = ["npc_id: exact NPC ID from the supplied cast"]
        if self.preferences.emotion_palette:
            fields.append(
                "emotion: ONE dominant current overall feeling from "
                + ", ".join(EMOTIONS)
                + "; intensity: integer 0-100, supplied by you, not a relationship score"
            )
        if self.preferences.character_thoughts:
            fields.append(
                f"thought: one short fictional in-character inner sentence, at most {MAX_THOUGHT} "
                "characters, in the story language; never model reasoning, instructions or analysis"
            )
        return (
            "PORTRAIT PRESENTATION (enabled for this reply): Write the complete story normally, "
            "then append exactly "
            + OPEN
            + '{"npcs":[...]}'
            + CLOSE
            + ". The footer is private UI data, not spoken dialogue. "
            "JSON keys and schema-defined enum identifiers remain in English, regardless of "
            "the requested story language. Prose-only formatting and private-guidance rules "
            "apply to the visible story, not these explicitly enabled UI fields. "
            "Each entry contains " + "; ".join(fields) + ". "
            f"Only include relevant NPCs from this cast, at most {MAX_NPCS}, once each. "
            "These enabled session display options work without NPC Personality; return the "
            "requested fields even when no psychological appraisals are provided. "
            "Describe their overall state NOW, whatever its cause; it is not necessarily directed "
            "at the player. Respect established identity and psychological appraisals when provided. "
            "General activation is not sexual arousal. "
            "Use unknown or omit an entry when unassessed; unknown never means calm. "
            "Do not invent events, possessions, knowledge, agreement or personality changes for "
            "this display. Do not add protagonist thoughts. Do not include disabled fields. "
            "Nothing follows the closing tag. NPC cast: "
            + json.dumps(self.catalog, ensure_ascii=False)
        )

    def feed(self, delta: str) -> str:
        self.output_chars += len(delta)
        visible = self.stream.feed(delta) if self.preferences.enabled else delta
        self.body += visible
        return visible

    def finish(self) -> str:
        tail = self.stream.finish() if self.preferences.enabled else ""
        self.body += tail
        if self.preferences.enabled:
            self._collect(self.body, self.stream)
        return tail

    def clean(self, text: str) -> str:
        if not self.preferences.enabled:
            return text
        stream = FooterStream()
        visible = stream.feed(text) + stream.finish()
        self._collect(visible, stream)
        return visible

    def payload(self, text: str) -> dict | None:
        value = self.candidates.get(source_hash(text))
        if value is None or not self.deferred_actor_ids:
            return value
        npcs = {
            key: cue for key, cue in value["npcs"].items() if key not in self.deferred_actor_ids
        }
        return {**value, "npcs": npcs} if npcs else None

    def diagnostic(self, text: str, *, completed: bool) -> str:
        if not self.preferences.enabled:
            return "disabled"
        if not self.catalog:
            return "no_visible_cast"
        if not completed:
            return "incomplete_narration"
        if self.payload(text):
            return "available"
        if source_hash(text) in self.candidates:
            return "no_valid_entries"
        return self.outcomes.get(
            source_hash(text), "source_mismatch" if self.candidates else "missing_footer"
        )

    def _note(self, text: str, reason: str) -> None:
        if len(self.outcomes) < 8:
            self.outcomes.setdefault(source_hash(text), reason)

    def _collect(self, text: str, stream: FooterStream) -> None:
        if stream.overflow:
            self._note(text, "footer_too_large")
        elif stream.complete:
            self._capture(text, stream.footer)
        else:
            self._note(text, "incomplete_footer" if stream.started else "missing_footer")

    def _capture(self, text: str, footer: str) -> None:
        try:
            data = json.loads(footer)
        except (ValueError, TypeError, RecursionError):
            self._note(text, "invalid_json")
            return
        entries = data.get("npcs") if isinstance(data, dict) else None
        if not isinstance(entries, list) or len(entries) > MAX_NPCS:
            self._note(text, "invalid_entries")
            return
        states = {}
        for entry in entries:
            identifier, cue = self._entry(entry)
            if identifier and cue and identifier not in states:
                states[identifier] = cue
        if states and len(self.candidates) < 4:
            key = source_hash(text)
            self.candidates[key] = {"version": 1, "source_hash": key, "npcs": states}
        if not states:
            self._note(text, "no_valid_entries")

    @sync_step("npc.presentation.validate_entry")
    def _entry(self, entry: Any) -> tuple[str | None, dict | None]:
        if not isinstance(entry, dict) or not isinstance(entry.get("npc_id"), str):
            return None, None
        if entry["npc_id"] not in self.catalog or entry["npc_id"] in self.deferred_actor_ids:
            return None, None
        emotion = Cue()
        if self.preferences.emotion_palette:
            try:
                emotion = Cue.model_validate(
                    {"emotion": entry.get("emotion"), "intensity": entry.get("intensity")}
                )
            except ValidationError:
                emotion = Cue()
        thought = entry.get("thought")
        if (
            not self.preferences.character_thoughts
            or not isinstance(thought, str)
            or not thought.strip()
            or len(thought) > MAX_THOUGHT
        ):
            thought = None
        else:
            thought = " ".join(thought.split())
        if emotion.emotion is None or emotion.intensity is None:
            emotion = Cue()
        emotion.thought = thought
        if emotion.emotion is None and thought is None:
            return None, None
        return entry["npc_id"], emotion.model_dump(exclude_none=True)


def prepare(manager: Any, entities: list[Any]) -> PresentationTurn:
    preferences = effective(manager.state)
    turn = PresentationTurn(preferences, _catalog(manager, entities) if preferences.enabled else {})
    manager._portrait_presentation = turn
    return turn


def clean_candidate(manager: Any, text: str) -> str:
    turn = getattr(manager, "_portrait_presentation", None)
    return turn.clean(text) if isinstance(turn, PresentationTurn) else text


def output_reminder(manager: Any) -> str:
    turn = getattr(manager, "_portrait_presentation", None)
    return turn.reminder if isinstance(turn, PresentationTurn) else ""


def defer_characters(manager: Any, actor_ids: set[str]) -> None:
    """A locally rejected intention cannot add new private portrait thoughts or feelings."""
    turn = getattr(manager, "_portrait_presentation", None)
    if isinstance(turn, PresentationTurn):
        turn.deferred_actor_ids.update(actor_ids)


def diagnose(manager: Any, text: str, *, completed: bool) -> None:
    turn = getattr(manager, "_portrait_presentation", None)
    if isinstance(turn, PresentationTurn):
        report(manager, turn, text, completed=completed)
