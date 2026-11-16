"""Ephemeral lexical/rhythm measurements, not a judgement of narrative quality."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil
from statistics import mean, pstdev

from backend.core.content_language import default_language
from backend.engine.narrator.flow_text import ReplySample, samples
from backend.engine.narrator.settings import NarrationFlow


@dataclass(frozen=True)
class FlowReport:
    profile: NarrationFlow
    language: str
    replies: int = 0
    characters: int = 0
    tokens: int = 0
    truncated: bool = False
    phrase_replies: int = 0
    opening_replies: int = 0
    closing_replies: int = 0
    gesture_replies: int = 0
    ellipsis_count: int = 0
    dash_count: int = 0
    question_closings: int = 0
    length_cv: float | None = None
    uniform_sentence_replies: int = 0
    signals: tuple[str, ...] = ()


def analyze_flow(
    texts: Sequence[str], profile: NarrationFlow = "gentle", language: str | None = None
) -> FlowReport:
    if profile not in {"off", "gentle", "balanced"}:
        raise ValueError("Unsupported narration flow profile.")
    if profile == "off":
        return FlowReport(profile, default_language(language))
    rows, truncated = samples(texts)
    complete = [row for row in rows if not row.truncated]
    lengths = [row.reply_characters for row in rows]
    variation = pstdev(lengths) / mean(lengths) if len(lengths) >= 3 else None
    report = FlowReport(
        profile=profile,
        language=default_language(language),
        replies=len(rows),
        characters=sum(row.characters for row in rows),
        tokens=sum(row.tokens for row in rows),
        truncated=truncated,
        phrase_replies=_support([row.phrases for row in rows]),
        opening_replies=_support([row.openings for row in rows]),
        closing_replies=_support(
            [frozenset([row.closing]) if row.closing else frozenset() for row in complete]
        ),
        gesture_replies=_support([row.gestures for row in rows]),
        ellipsis_count=sum(row.ellipses for row in rows),
        dash_count=sum(row.dashes for row in rows),
        question_closings=sum(row.question_closing for row in complete),
        length_cv=round(variation, 4) if variation is not None else None,
        uniform_sentence_replies=max(
            Counter(row.sentences for row in complete).values(), default=0
        ),
    )
    return _with_signals(report, rows)


def _support(values: Sequence[frozenset]) -> int:
    return max(Counter(value for group in values for value in group).values(), default=0)


def _with_signals(report: FlowReport, rows: tuple[ReplySample, ...]) -> FlowReport:
    from dataclasses import replace

    minimum, fraction = (4, 0.75) if report.profile == "gentle" else (3, 0.6)
    if report.replies < minimum:
        return report
    support = max(3, ceil(report.replies * fraction))
    signals = []
    for name, count in (
        ("phrases", report.phrase_replies),
        ("openings", report.opening_replies),
        ("closings", max(report.closing_replies, report.question_closings)),
        ("gestures", report.gesture_replies),
    ):
        if count >= support:
            signals.append(name)
    chars = max(report.characters, 1)
    pause_budget, dash_budget = (5, 8) if report.profile == "gentle" else (3, 5)
    pauses = sum(row.ellipses > 0 for row in rows)
    dashes = sum(row.dashes > 0 for row in rows)
    if (
        pauses >= support
        and report.ellipsis_count >= minimum * 2
        and report.ellipsis_count * 1000 / chars > pause_budget
    ):
        signals.append("ellipses")
    if (
        dashes >= support
        and report.dash_count >= minimum * 2
        and report.dash_count * 1000 / chars > dash_budget
    ):
        signals.append("dashes")
    uniform = report.length_cv is not None and report.length_cv <= 0.08
    if uniform and (signals or report.profile == "balanced"):
        signals.append("rhythm")
    return replace(report, signals=tuple(signals))
