"""Chunk descriptors are local, bounded and exact before SQL import begins."""

import hashlib
import io
import json
import zipfile
from copy import deepcopy

import pytest

from backend.engine import archive_safety
from backend.engine.world_info import archive_parts
from backend.engine.world_info.archive_parts import prepare_world_info, read_world_info
from backend.engine.world_info.portable_schema import PortableWorldInfo
from tests.world_info_fixture import corpus


def bundle(manifest, parts):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("session.json", json.dumps(manifest))
        for path, payload in parts:
            archive.writestr(path, payload, compress_type=zipfile.ZIP_STORED)
    return zipfile.ZipFile(io.BytesIO(output.getvalue()))


def prepared(monkeypatch):
    monkeypatch.setattr(archive_parts, "INLINE_LIMIT_BYTES", 256)
    original = {"world_info": corpus("assets/harbor: 港の記録 — خريطة الميناء")}
    manifest, parts = prepare_world_info(original)
    return original, manifest, parts


def test_small_inline_corpus_and_legacy_absent_section_are_unchanged():
    original = {"world_info": corpus(), "session_state": {"clock": 480}}
    manifest, parts = prepare_world_info(original)
    assert manifest is original and parts == []
    with bundle(manifest, []) as archive:
        assert read_world_info(archive, manifest["world_info"]) == original["world_info"]
    with bundle({}, []) as archive:
        assert read_world_info(archive, None) is None


def test_parts_roundtrip_exact_source_evidence_grouping_and_status(monkeypatch):
    original, manifest, parts = prepared(monkeypatch)
    assert len(parts) > 1 and manifest["world_info"]["format"] == archive_parts.FORMAT
    assert b"\\u6e2f" not in b"".join(payload for _, payload in parts)
    with bundle(manifest, parts) as archive:
        restored = read_world_info(archive, manifest["world_info"])
    assert restored == original["world_info"]
    PortableWorldInfo.model_validate(restored)


@pytest.mark.parametrize(
    "mutation",
    [
        "outside_path",
        "network_path",
        "missing_part",
        "undeclared_part",
        "duplicate_reference",
        "wrong_size",
        "wrong_hash",
        "wrong_kind",
        "wrong_rows",
        "wrong_count",
        "wrong_order",
        "wrong_version",
        "boolean_size",
        "too_many_parts",
        "noncanonical_path",
        "duplicate_key",
        "invalid_utf8",
        "nonfinite",
        "part_shape",
        "zip_traversal",
        "part_too_large",
    ],
)
def test_malformed_descriptor_or_part_is_rejected_before_materialization(monkeypatch, mutation):
    _, manifest, parts = prepared(monkeypatch)
    section = manifest["world_info"]
    first = section["parts"][0]
    body_mutations = {
        "duplicate_key": parts[0][1].replace(b'{"version":1,', b'{"version":1,"version":1,', 1),
        "invalid_utf8": b"\xff",
        "nonfinite": b'{"version":1,"kind":"sources","rows":[{"id":NaN}]}',
        "part_shape": b"[]",
    }
    if mutation in body_mutations:
        body = body_mutations[mutation]
        parts[0] = (parts[0][0], body)
        first.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
    changes = {
        "outside_path": lambda: first.update(path="../source.json"),
        "network_path": lambda: first.update(path="https://example.invalid/source.json"),
        "missing_part": lambda: parts.pop(0),
        "undeclared_part": lambda: parts.append(("world-info/part-99999.json", b"{}")),
        "duplicate_reference": lambda: section["parts"].append(deepcopy(first)),
        "wrong_size": lambda: first.update(bytes=first["bytes"] + 1),
        "wrong_hash": lambda: first.update(sha256="0" * 64),
        "wrong_kind": lambda: first.update(kind="entries"),
        "wrong_rows": lambda: first.update(rows=first["rows"] + 1),
        "wrong_count": lambda: section["counts"].update(entries=section["counts"]["entries"] + 1),
        "wrong_order": section["parts"].reverse,
        "wrong_version": lambda: section.update(version=2),
        "boolean_size": lambda: first.update(bytes=True),
        "too_many_parts": lambda: section.update(parts=[first] * 129),
        "noncanonical_path": lambda: first.update(path="world-info/part-0.json"),
        "zip_traversal": lambda: parts.append(("../source.json", b"{}")),
        "part_too_large": lambda: first.update(bytes=archive_safety.MAX_ENTRY_BYTES),
    }
    if mutation in changes:
        changes[mutation]()
    with bundle(manifest, parts) as archive, pytest.raises(ValueError):
        read_world_info(archive, section)


def test_inline_or_missing_descriptor_cannot_silently_discard_parts(monkeypatch):
    original, manifest, parts = prepared(monkeypatch)
    for section in (None, original["world_info"]):
        with bundle(manifest, parts) as archive, pytest.raises(ValueError, match="undeclared"):
            read_world_info(archive, section)


def test_a_single_source_row_can_exceed_chunk_target_without_text_fragmentation():
    payload = corpus()
    text = "港" * 1_400_000
    payload["sources"][0].update(current_revision=1, published_revision=None)
    revision = payload["revisions"][0]
    revision.update(
        content=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        input_bytes=len(text.encode()),
        input_characters=len(text),
        status="uploaded",
        cursor=0,
        total_batches=0,
        processed_characters=0,
        entries_count=0,
        facts_count=0,
        processing_language=None,
    )
    payload.update(revisions=[revision], entries=[])
    manifest, parts = prepare_world_info({"world_info": payload})
    assert any(len(body) > archive_parts.INLINE_LIMIT_BYTES for _, body in parts)
    assert all(len(body) < archive_safety.MAX_ENTRY_BYTES for _, body in parts)
    with bundle(manifest, parts) as archive:
        restored = read_world_info(archive, manifest["world_info"])
    assert restored["revisions"][0]["content"] == text
    PortableWorldInfo.model_validate(restored)
