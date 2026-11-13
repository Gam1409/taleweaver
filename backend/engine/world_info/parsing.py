"""Bounded inert source parsing with exact Markdown spans and JSON pointers."""

import hashlib
import json
import math
from collections.abc import Iterator, Mapping
from dataclasses import asdict
from typing import Any

from backend.engine.world_info import limits
from backend.engine.world_info.types import (
    Evidence,
    SourceBatch,
    SourceFormat,
    SourcePassage,
    SourcePlan,
    validate_text,
)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON source contains duplicate keys.")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise ValueError("JSON source contains non-finite numbers.")


def _json_values(content: str) -> Iterator[tuple[str, str]]:
    try:
        root = json.loads(
            content.removeprefix("\ufeff"),
            object_pairs_hook=_unique_keys,
            parse_constant=_nonfinite,
        )
    except (json.JSONDecodeError, RecursionError, OverflowError) as exc:
        raise ValueError("JSON source is invalid or exceeds its nesting budget.") from exc
    pending = [(root, "", 0)]
    count = 0
    while pending:
        value, pointer, depth = pending.pop()
        count += 1
        if depth > limits.MAX_JSON_DEPTH or count > limits.MAX_JSON_NODES:
            raise ValueError("JSON source exceeds its depth or node budget.")
        validate_text(pointer)
        if isinstance(value, (dict, list)):
            children = value.items() if isinstance(value, dict) else enumerate(value)
            pending.extend(
                (item, pointer + "/" + str(key).replace("~", "~0").replace("/", "~1"), depth + 1)
                for key, item in reversed(list(children))
            )
            continue
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("JSON source contains non-finite numbers.")
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        validate_text(text)
        if text.strip():
            yield pointer, text


def _passages(content: str, format: SourceFormat) -> Iterator[SourcePassage]:
    sources = [(None, content)] if format == "md" else _json_values(content)
    number = 0
    for pointer, text in sources:
        start = 0
        while start < len(text):
            size = min(limits.MAX_PASSAGE_CHARACTERS, limits.MAX_BATCH_CHARACTERS // 2 - 128)
            end = min(start + max(1, size), len(text))
            passage = _fit_passage(f"p{number}", text, start, end, pointer)
            yield passage
            number += 1
            start = passage.end


def _fit_passage(
    identity: str, text: str, start: int, end: int, pointer: str | None
) -> SourcePassage:
    passage = SourcePassage(identity, text[start:end], start, end, pointer)
    while len(json.dumps(asdict(passage), ensure_ascii=False)) > limits.MAX_BATCH_CHARACTERS - 2:
        end = start + (end - start) // 2
        if end <= start:
            raise ValueError("Source passage metadata exceeds its batch budget.")
        passage = SourcePassage(identity, text[start:end], start, end, pointer)
    return passage


def batch_payload(batch: SourceBatch) -> list[dict[str, Any]]:
    return [asdict(passage) for passage in batch.passages]


def _batches(passages: Iterator[SourcePassage]) -> tuple[SourceBatch, ...]:
    batches: list[SourceBatch] = []
    current: list[SourcePassage] = []
    for passage in passages:
        candidate = SourceBatch(len(batches), tuple([*current, passage]))
        if (
            len(json.dumps(batch_payload(candidate), ensure_ascii=False))
            <= limits.MAX_BATCH_CHARACTERS
        ):
            current.append(passage)
            continue
        if not current:
            raise ValueError("Source passage metadata exceeds its batch budget.")
        batches.append(SourceBatch(len(batches), tuple(current)))
        current = [passage]
        if (
            len(json.dumps(batch_payload(SourceBatch(0, tuple(current))), ensure_ascii=False))
            > limits.MAX_BATCH_CHARACTERS
        ):
            raise ValueError("Source passage metadata exceeds its batch budget.")
        if len(batches) >= limits.MAX_BATCHES:
            raise ValueError("Source exceeds its processing batch budget.")
    if current:
        batches.append(SourceBatch(len(batches), tuple(current)))
    if not batches or len(batches) > limits.MAX_BATCHES:
        raise ValueError("Source is empty or exceeds its processing batch budget.")
    return tuple(batches)


def parse_source(content: str, format: SourceFormat) -> SourcePlan:
    """Parse unchanged text; offsets are Python Unicode codepoints, never UTF-8 bytes."""
    if format not in {"md", "json"}:
        raise ValueError("Only Markdown and JSON sources are supported.")
    if not content.strip() or len(content) > limits.MAX_SOURCE_CHARACTERS:
        raise ValueError("Source is empty or exceeds its character budget.")
    validate_text(content)
    raw = content.encode("utf-8")
    if len(raw) > limits.MAX_SOURCE_BYTES:
        raise ValueError("Source exceeds its byte budget.")
    return SourcePlan(
        format,
        hashlib.sha256(raw).hexdigest(),
        len(content),
        len(raw),
        _batches(_passages(content, format)),
    )


def validate_evidence(
    evidence: Evidence,
    plan: SourcePlan,
    *,
    passages: Mapping[str, SourcePassage] | None = None,
) -> None:
    """Verify a saved locator against the immutable source, not a model assertion."""
    index = passages if passages is not None else plan.passage_index
    passage = index.get(evidence.passage_id)
    if passage is None or evidence.source_hash != plan.source_hash:
        raise ValueError("Evidence source or passage does not match.")
    start, end = evidence.start - passage.start, evidence.end - passage.start
    if (
        evidence.pointer != passage.pointer
        or not 0 <= start < end <= len(passage.text)
        or passage.text[start:end] != evidence.quote
    ):
        raise ValueError("Evidence does not match its exact source location.")
