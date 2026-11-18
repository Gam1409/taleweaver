"""Select one existing speech anchor only when every surplus source is unambiguous."""

from collections import Counter

from backend.core.text_passages import Passage, spans
from backend.engine.chpm.passages import SharedReference, SharedReview
from backend.engine.chpm.schema import Decision


def _speaker(actor: str, names: dict[str, str], player_name: str | None) -> str | None:
    name = names.get(actor)
    if not name or not player_name or name.casefold() in {player_name.casefold(), "you"}:
        return None
    if sum(value.casefold() == name.casefold() for value in names.values()) != 1:
        return None
    return name


def _quoted(body: str) -> bool:
    for opening, closing in (('"', '"'), ("«", "»"), ("“", "”"), ("„", "“")):
        if not (body.startswith(opening) and body.endswith(closing)):
            continue
        inner = body[1:-1]
        return bool(inner.strip()) and opening not in inner and closing not in inner
    return False


def _own_speech(
    reference: SharedReference, occurrences: dict[str, Passage], text: str, name: str
) -> bool:
    passage = occurrences.get(reference.passage_id or "")
    if passage is None:
        return False
    start = text.rfind("\n", 0, passage.start) + 1
    end = text.find("\n", passage.end)
    original = text[start : end if end >= 0 else len(text)]
    line = original.lstrip()
    line_start = start + len(original) - len(line)
    # This is an explicit source label, not a guess from a pronoun, verb or writing style.
    for label in (f"{name}:", f"**{name}:**", f"**{name}**:"):
        if not line.startswith(label):
            continue
        suffix = line[len(label) :]
        body = suffix.strip()
        if not _quoted(body):
            return False
        speech_start = line_start + len(label) + len(suffix) - len(suffix.lstrip()) + 1
        speech_end = speech_start + len(body) - 2
        return bool(text[max(passage.start, speech_start) : min(passage.end, speech_end)].strip())
    return False


def _eligible(
    actor: str,
    review: SharedReview,
    decisions: dict[str, Decision],
    names: dict[str, str],
    player_name: str | None,
    text: str,
    occurrences: dict[str, Passage],
) -> bool:
    decision = decisions.get(actor)
    if decision is None or decision.selected.agenda_change or decision.selected.kind == "DEFER":
        return False
    name = _speaker(actor, names, player_name)
    return bool(
        name
        and all(
            _own_speech(entry, occurrences, text, name)
            for entry in review.evidence
            if entry.actor_id == actor
        )
    )


def representative(
    review: SharedReview,
    *,
    decisions: dict[str, Decision],
    names: dict[str, str],
    player_name: str | None,
    text: str,
) -> SharedReview:
    """Caller has checked scope/current IDs; unknown authorship retains strict host validation.

    No agenda anchor is chosen, no quotations are joined, and no actions or world
    authority change. The provider's original DTO is retained for diagnostics.
    """
    if not review.matches or review.rejections:
        return review
    duplicates = {
        actor
        for actor, count in Counter(row.actor_id for row in review.evidence).items()
        if count > 1
    }
    if not duplicates:
        return review
    # A mutated internal DTO must not use reduction to bypass the existing global bounds.
    checked = SharedReview.model_validate(review.model_dump())
    occurrences = spans(text)
    eligible = {
        actor
        for actor in duplicates
        if _eligible(actor, checked, decisions, names, player_name, text, occurrences)
    }
    if not eligible:
        return review
    seen: set[str] = set()
    selected = []
    for entry in checked.evidence:
        if entry.actor_id in eligible and entry.actor_id in seen:
            continue
        selected.append(entry)
        seen.add(entry.actor_id)
    return review.model_copy(update={"evidence": selected})
