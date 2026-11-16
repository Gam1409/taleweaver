"""Only fictional source samples; imported documents remain inert exact data."""

import json
from dataclasses import replace

import pytest

from backend.engine.world_info import limits
from backend.engine.world_info.parsing import batch_payload, parse_source, validate_evidence
from backend.engine.world_info.types import Evidence


def passages(plan):
    return [passage for batch in plan.batches for passage in batch.passages]


def test_markdown_offsets_are_unicode_codepoints_and_preserve_inert_markup():
    source = "# 港の記録\nМаяк 🧭\n<script>alert(1)</script>\n![map](https://example.invalid/map)\n"
    plan = parse_source(source, "md")
    assert plan.characters == len(source)
    assert plan.bytes == len(source.encode())
    assert "".join(p.text for p in passages(plan)) == source
    assert all(p.pointer is None and source[p.start : p.end] == p.text for p in passages(plan))
    assert parse_source(source, "md") == plan


def test_maximum_plain_source_is_complete_and_within_shared_batch_limits():
    source = "a" * limits.MAX_SOURCE_CHARACTERS
    plan = parse_source(source, "md")
    assert len(plan.batches) <= limits.MAX_BATCHES
    assert "".join(p.text for p in passages(plan)) == source
    assert all(len(p.text) <= limits.MAX_PASSAGE_CHARACTERS for p in passages(plan))
    assert all(
        len(json.dumps(batch_payload(b), ensure_ascii=False)) <= limits.MAX_BATCH_CHARACTERS
        for b in plan.batches
    )
    with pytest.raises(ValueError, match="character budget"):
        parse_source(source + "a", "md")


def test_escaped_batch_sizes_and_tail_are_preserved():
    source = "a\n" * 6000 + "TAIL"
    plan = parse_source(source, "md")
    assert "".join(p.text for p in passages(plan)) == source
    assert all(
        len(json.dumps(batch_payload(b), ensure_ascii=False)) <= limits.MAX_BATCH_CHARACTERS
        for b in plan.batches
    )


def test_exact_utf8_byte_limit_and_multilingual_tail_are_preserved():
    source = "🧭" * min(limits.MAX_SOURCE_CHARACTERS, limits.MAX_SOURCE_BYTES // 4)
    plan = parse_source(source, "md")
    assert plan.bytes == min(limits.MAX_SOURCE_CHARACTERS * 4, limits.MAX_SOURCE_BYTES)
    assert "".join(p.text for p in passages(plan)) == source
    with pytest.raises(ValueError):
        parse_source(source + "🧭", "md")


def test_long_json_scalar_offsets_restart_only_for_a_new_pointer():
    source = json.dumps({"first": "あ" * 9000, "second": "مرحبا"}, ensure_ascii=False)
    rows = passages(parse_source(source, "json"))
    first = [p for p in rows if p.pointer == "/first"]
    assert "".join(p.text for p in first) == "あ" * 9000
    assert first[0].start == 0 and first[-1].end == 9000
    assert all(a.end == b.start for a, b in zip(first, first[1:], strict=False))
    assert rows[-1].pointer == "/second" and rows[-1].start == 0


def test_batch_count_rejects_before_any_source_is_silently_dropped(monkeypatch):
    monkeypatch.setattr(limits, "MAX_BATCHES", 1)
    with pytest.raises(ValueError, match="batch budget"):
        parse_source("x" * 9000, "md")


def test_json_pointers_preserve_duplicate_values_and_escaped_keys():
    plan = parse_source('{"a/b":{"~key":["港\\n灯台","港\\n灯台",true,null,12]}}', "json")
    rows = passages(plan)
    assert [p.pointer for p in rows] == [f"/a~1b/~0key/{i}" for i in range(5)]
    assert [p.text for p in rows] == ["港\n灯台", "港\n灯台", "true", "null", "12"]
    assert rows[0].start == 0 and rows[0].end == len("港\n灯台")
    assert passages(parse_source('"root"', "json"))[0].pointer == ""
    assert passages(parse_source('\ufeff{"value":"root"}', "json"))[0].text == "root"


@pytest.mark.parametrize(
    "source",
    [
        '{"x":1,"x":2}',
        '{"x":NaN}',
        "[Infinity]",
        "[1e10000]",
        '{"x":1,}',
        '"\\ud800"',
        '{"\\udfff":1}',
    ],
)
def test_json_rejects_ambiguous_nonfinite_invalid_or_surrogate_data(source):
    with pytest.raises(ValueError):
        parse_source(source, "json")


@pytest.mark.parametrize("source", ["", " \n\t", "bad\x00data", "bad\ud800data"])
def test_invalid_source_text_is_rejected(source):
    with pytest.raises(ValueError):
        parse_source(source, "md")


@pytest.mark.parametrize("source", ["{}", "[]", '""'])
def test_json_without_supported_scalar_content_is_rejected(source):
    with pytest.raises(ValueError, match="empty"):
        parse_source(source, "json")


def test_json_depth_and_node_count_exact_boundaries():
    source = "[" * limits.MAX_JSON_DEPTH + '"leaf"' + "]" * limits.MAX_JSON_DEPTH
    assert passages(parse_source(source, "json"))[0].text == "leaf"
    with pytest.raises(ValueError, match="depth"):
        parse_source("[" + source + "]", "json")
    assert parse_source(json.dumps([[]] * (limits.MAX_JSON_NODES - 2) + ["leaf"]), "json")
    with pytest.raises(ValueError, match="node budget"):
        parse_source(json.dumps([[]] * (limits.MAX_JSON_NODES - 1) + ["leaf"]), "json")


def test_large_json_pointer_has_bounded_failure_instead_of_prompt_expansion():
    with pytest.raises(ValueError, match="metadata"):
        parse_source(json.dumps({"x" * limits.MAX_BATCH_CHARACTERS: "value"}), "json")


@pytest.mark.parametrize(
    "format,source,quote",
    [("md", "🧭 Маяк над бухтой.", "Маяк"), ("json", '{"港":"Маяк над бухтой."}', "Маяк")],
)
def test_persisted_evidence_validates_exact_locator_and_source_hash(format, source, quote):
    plan = parse_source(source, format)
    passage = passages(plan)[0]
    start = passage.start + passage.text.index(quote)
    evidence = Evidence(
        passage_id=passage.id,
        pointer=passage.pointer,
        start=start,
        end=start + len(quote),
        quote=quote,
        source_hash=plan.source_hash,
    )
    validate_evidence(evidence, plan)
    for update in [
        {"pointer": "/wrong"},
        {"start": start + 1, "end": start + 1 + len(quote)},
        {"source_hash": "0" * 64},
        {"passage_id": "p999"},
    ]:
        with pytest.raises(ValueError):
            validate_evidence(evidence.model_copy(update=update), plan)
    with pytest.raises(ValueError):
        validate_evidence(evidence, replace(plan, source_hash="0" * 64))


def test_bulk_evidence_uses_immutable_shared_index_and_cached_decoded_prefixes():
    plan = parse_source('[1e2,"Маяк"]', "json")
    index = plan.passage_index
    assert index is plan.passage_index
    assert plan.character_offsets is plan.character_offsets
    assert plan.character_offsets[0] == 0
    assert plan.character_offsets[-1] == sum(
        len(p.text) for batch in plan.batches for p in batch.passages
    )
    assert len(plan.character_offsets) == len(plan.batches) + 1
    passage = next(iter(index.values()))
    evidence = Evidence(
        passage_id=passage.id,
        pointer=passage.pointer,
        start=passage.start,
        end=passage.end,
        quote=passage.text,
        source_hash=plan.source_hash,
    )
    validate_evidence(evidence, plan)
    validate_evidence(evidence, plan, passages=index)
    with pytest.raises(TypeError):
        index["extra"] = passage
