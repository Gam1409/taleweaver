"""Adversarial notebook inputs stay inert, atomic, and integrity checked."""

import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.engine.chpm import notebook_requests
from backend.engine.chpm.agent_tools import Tools
from backend.engine.chpm.errors import ChpmError
from backend.engine.chpm.notebook import NotebookError, NotebookWorkspace, codec, decode, encode
from backend.engine.chpm.notebook_archive import FORMAT, append_part, create_archive, read_notebooks
from backend.engine.chpm.notebook_portability import import_notebooks
from backend.engine.chpm.notebook_store import load_payload, load_snapshot, persist_workspace
from backend.engine.chpm.notebook_tools import NotebookDraft, request_summary, result_summary
from backend.models.game_session import GameSession
from backend.models.npc_notebook import NpcNotebook
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_state import mind
from tests.test_chpm_kernel import observation
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@pytest.mark.parametrize(
    "raw",
    [
        "1e999",
        "-1e999",
        '{"a":1,"\\u0061":2}',
        '{"\\udfff":1}',
        '{"safe":[{"safe":"\\ud800"}]}',
    ],
)
def test_encoded_duplicates_overflow_and_nested_invalid_unicode_are_rejected(raw):
    with pytest.raises(NotebookError):
        decode(raw)


def test_valid_unicode_surrogate_pair_has_one_canonical_scalar():
    assert encode(decode('"\\ud83d\\ude42"')) == '"🙂"'.encode()


@pytest.mark.parametrize("name", [None, True, 1, [], {}])
def test_malformed_operation_name_is_a_local_error_and_discards_earlier_edits(name):
    workspace = NotebookWorkspace(b'{"nested":{"kept":1}}', revision=3)
    operations = [
        {"op": "replace", "path": "/nested/kept", "value_json": "2"},
        {"op": name, "path": "/nested/kept", "value_json": "3"},
    ]
    with pytest.raises(NotebookError):
        workspace.edit(operations, expected_revision=3)
    assert workspace.canonical_bytes == b'{"nested":{"kept":1}}'
    assert workspace.revision == 3 and not workspace.changed


@pytest.mark.parametrize("pointer", [None, False, 1, [], {}])
@pytest.mark.parametrize("method", ["read", "write", "delete"])
def test_non_string_pointer_cannot_resolve_attributes_or_mutate(pointer, method):
    workspace = NotebookWorkspace(b'{"kept":1}')
    kwargs = {} if method == "read" else {"expected_revision": 0}
    arguments = (pointer, "2") if method == "write" else (pointer,)
    with pytest.raises(NotebookError):
        getattr(workspace, method)(*arguments, **kwargs)
    assert workspace.canonical_bytes == b'{"kept":1}' and workspace.revision == 0


def test_pointer_escape_order_and_special_keys_are_literal_json_members():
    value = {"~1": {"__class__": {"..": "private note"}}, "a": {"00": "object key"}}
    workspace = NotebookWorkspace(encode(value))
    assert json.loads(workspace.read("/~01/__class__/..")["json_fragment"]) == "private note"
    assert json.loads(workspace.read("/a/00")["json_fragment"]) == "object key"
    with pytest.raises(NotebookError):
        workspace.read("/__dict__")
    assert workspace.canonical_bytes == encode(value)


def test_nested_patch_test_distinguishes_booleans_from_numbers_atomically():
    workspace = NotebookWorkspace(b'{"nested":{"array":[true,null]}}')
    with pytest.raises(NotebookError, match="did not match"):
        workspace.edit(
            [
                {"op": "add", "path": "/draft", "value_json": "1"},
                {"op": "test", "path": "/nested", "value_json": '{"array":[1,null]}'},
            ],
            expected_revision=0,
        )
    assert workspace.canonical_bytes == b'{"nested":{"array":[true,null]}}'
    assert workspace.revision == 0


@pytest.mark.parametrize(
    ("model", "arguments"),
    [
        (notebook_requests.NotebookRead, {"tool": "notebook_read"}),
        (
            notebook_requests.NotebookWrite,
            {"tool": "notebook_write", "expected_revision": 0, "value_json": "2"},
        ),
        (notebook_requests.NotebookDelete, {"tool": "notebook_delete", "expected_revision": 0}),
        (notebook_requests.NotebookOperation, {"op": "replace", "value_json": "2"}),
    ],
)
def test_typed_notebook_paths_preserve_significant_whitespace(model, arguments):
    request = model.model_validate({**arguments, "path": "/ member "})
    assert request.path == "/ member "


@pytest.mark.parametrize("field", ["owner_id", "session_id", "npc_id", "actor_id", "branch_id"])
def test_model_tool_arguments_cannot_supply_storage_scope(field):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        notebook_requests.NotebookWrite.model_validate(
            {
                "tool": "notebook_write",
                "expected_revision": 0,
                "value_json": "2",
                field: "other-scope",
            }
        )


def test_typed_pointer_rejects_lone_surrogate_before_tool_audit_encoding():
    with pytest.raises(ValidationError):
        notebook_requests.NotebookRead.model_validate({"tool": "notebook_read", "path": "/\ud800"})


def notebook_row(owner_id, payload=b'{"private":"owner note"}', **scope):
    return NpcNotebook(
        user_id=owner_id,
        session_id=scope.get("session_id", "portrait-session"),
        npc_id=scope.get("npc_id", "NPC_NEW"),
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        payload=payload,
        revision=1,
    )


@pytest.mark.parametrize("field", ["user_id", "session_id", "npc_id"])
async def test_current_document_cannot_override_host_bound_scope(portrait_world, field):
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        row = notebook_row(session.user_id)
        setattr(row, field, "other-session" if field == "session_id" else "other-scope")
        db.add(row)
        await db.flush()
        assert await load_payload(db, mind("NPC_NEW", session.id), session.user_id) == b"{}"


async def test_foreign_owner_cannot_read_the_current_document(portrait_world):
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        db.add(notebook_row(session.user_id))
        await db.flush()
        with pytest.raises(ChpmError, match="session is unavailable"):
            await load_payload(db, mind("NPC_NEW", session.id), "other-owner")


async def test_corrupt_current_document_fails_before_it_reaches_a_workspace(portrait_world):
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        row = notebook_row(session.user_id)
        row.payload = row.payload.replace(b"owner", b"other")
        db.add(row)
        await db.flush()
        with pytest.raises(ChpmError, match="integrity check failed"):
            await load_snapshot(db, mind("NPC_NEW", session.id), session.user_id)


async def test_multiple_local_edits_replace_one_row_and_preserve_objective_state(portrait_world):
    actor = mind("NPC_NEW", "portrait-session")
    original = actor.model_dump(mode="json")
    workspace = NotebookWorkspace()
    workspace.write("/first", '"one"', expected_revision=0)
    workspace.write("/second", '"two"', expected_revision=1)
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        await persist_workspace(db, actor, workspace, owner_id=session.user_id)
        saved = await load_snapshot(db, actor, session.user_id)
        assert saved.payload == workspace.canonical_bytes and saved.revision == 2
        replacement = NotebookWorkspace(saved.payload, revision=saved.revision)
        replacement.write("", '{"current":"replacement"}', expected_revision=2)
        await persist_workspace(db, actor, replacement, owner_id=session.user_id)
        rows = (await db.scalars(select(NpcNotebook))).all()
        assert len(rows) == 1
        assert await load_payload(db, actor, session.user_id) == b'{"current":"replacement"}'
    assert actor.model_dump(mode="json") == original


async def test_stale_draft_cannot_replace_a_newer_current_document(portrait_world):
    actor = mind("NPC_NEW", "portrait-session")
    first, stale = NotebookWorkspace(), NotebookWorkspace()
    first.write("/note", '"accepted"', expected_revision=0)
    stale.write("/note", '"discarded"', expected_revision=0)
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        await persist_workspace(db, actor, first, owner_id=session.user_id)
        with pytest.raises(ChpmError, match="changed while this turn"):
            await persist_workspace(db, actor, stale, owner_id=session.user_id)
        assert await load_payload(db, actor, session.user_id) == b'{"note":"accepted"}'
        assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 1


async def test_outer_rollback_discards_all_npc_writes_and_allows_clean_retry(portrait_world):
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        owner_id = session.user_id
        session.status = "paused"
        db.add(
            WorldEntity(
                id="peer-npc",
                session_id=session.id,
                entity_type="NPC",
                name="Peer",
                description="A second notebook owner.",
                current_scene_id="TOWER",
            )
        )
        await db.flush()
        for actor_id in ("NPC_NEW", "peer-npc"):
            workspace = NotebookWorkspace()
            workspace.write("/draft", '"cancelled"', expected_revision=0)
            await persist_workspace(
                db, mind(actor_id, "portrait-session"), workspace, owner_id=owner_id
            )
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 0
        workspace = NotebookWorkspace()
        workspace.write("/draft", '"accepted"', expected_revision=0)
        actor = mind("NPC_NEW", "portrait-session")
        await persist_workspace(db, actor, workspace, owner_id=owner_id)
        assert await load_payload(db, actor, owner_id) == b'{"draft":"accepted"}'
        assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 1


async def test_insert_after_only_reads_still_waits_for_the_outer_commit(portrait_world):
    actor = mind("NPC_NEW", "portrait-session")
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        owner_id = session.user_id
        workspace = NotebookWorkspace()
        workspace.write("/draft", '"cancelled"', expected_revision=0)
        await persist_workspace(db, actor, workspace, owner_id=owner_id)
        await db.rollback()
        assert await load_payload(db, actor, owner_id) == b"{}"
        assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 0


async def test_update_after_only_reads_still_waits_for_the_outer_commit(portrait_world):
    actor = mind("NPC_NEW", "portrait-session")
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        owner_id = session.user_id
        db.add(notebook_row(owner_id, b'{"draft":"accepted"}'))
        await db.commit()
        saved = await load_snapshot(db, actor, owner_id)
        workspace = NotebookWorkspace(saved.payload, revision=saved.revision)
        workspace.write("/draft", '"cancelled"', expected_revision=saved.revision)
        await persist_workspace(db, actor, workspace, owner_id=owner_id)
        await db.rollback()
        assert await load_payload(db, actor, owner_id) == b'{"draft":"accepted"}'
        assert (await load_snapshot(db, actor, owner_id)).revision == 1
        assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 1


def portable_row():
    return json.dumps(
        {
            "npc_id": "NPC_NEW",
            "byte_size": 2,
            "sha256": hashlib.sha256(b"{}").hexdigest(),
            "document": {},
        },
        separators=(",", ":"),
    ).encode()


def portable_zip(payload):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("npc-notebooks/part-00000.json", payload)
    stream.seek(0)
    return zipfile.ZipFile(stream)


def portable_descriptor(payload):
    return {
        "format": FORMAT,
        "version": 1,
        "rows": 1,
        "parts": [
            {
                "path": "npc-notebooks/part-00000.json",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "rows": 1,
            }
        ],
    }


def test_portable_descriptor_cannot_choose_a_path_outside_fixed_parts():
    payload = b"[" + portable_row() + b"]"
    descriptor = portable_descriptor(payload)
    descriptor["parts"][0]["path"] = "../outside.json"
    with portable_zip(payload) as archive, pytest.raises(ChpmError, match="descriptor is invalid"):
        read_notebooks(archive, descriptor)


def test_portable_part_hash_is_checked_before_rows_are_used():
    payload = b"[" + portable_row() + b"]"
    altered = payload.replace(b"NPC_NEW", b"NPC_OLD")
    with portable_zip(altered) as archive, pytest.raises(ChpmError, match="integrity check failed"):
        read_notebooks(archive, portable_descriptor(payload))


async def test_duplicate_portable_npc_rows_are_rejected_and_outer_rollback_is_complete(
    portrait_world,
):
    corpus = create_archive()
    append_part(corpus, [portable_row()])
    append_part(corpus, [portable_row()])
    async with TestSessionLocal() as db:
        session = await db.get(GameSession, "portrait-session")
        state = SimpleNamespace(session_id=session.id)
        with pytest.raises(ChpmError, match="NPC membership is invalid"):
            await import_notebooks(db, state, session.user_id, corpus)
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(NpcNotebook)) == 0


def test_depth_budget_accepts_exact_boundary_and_rejects_one_more_container():
    raw = b"[" * codec.MAX_DEPTH + b"0" + b"]" * codec.MAX_DEPTH
    value = decode(raw)
    assert encode(value) == raw
    with pytest.raises(NotebookError):
        decode(b"[" + raw + b"]")
    with pytest.raises(NotebookError):
        encode([value])


def test_node_budget_agrees_between_raw_parser_and_canonical_encoder(monkeypatch):
    value = [None] * (codec.MAX_NODES - 1)
    canonical = encode(value)
    assert decode(canonical) == value
    with pytest.raises(NotebookError):
        encode([*value, None])

    def parser_must_not_run(*_args, **_kwargs):
        pytest.fail("An over-budget notebook reached the allocating JSON parser.")

    monkeypatch.setattr(codec.json, "loads", parser_must_not_run)
    with pytest.raises(NotebookError):
        decode(b"[null," + canonical[1:])


def test_shared_container_graph_cannot_expand_exponentially_during_encoding():
    value = []
    for _ in range(20):
        value = [value, value]
    with pytest.raises(NotebookError):
        encode(value)


def test_shared_large_strings_obey_the_aggregate_canonical_byte_quota():
    with pytest.raises(NotebookError, match="16,000,000"):
        encode(["x" * 1_000_000] * 17)


def test_structure_characters_inside_escaped_strings_do_not_spend_node_or_depth_budget():
    value = '[{"quoted":"\\\\\\""}],:' * (codec.MAX_DEPTH * 2)
    assert decode(json.dumps(value)) == value


def test_notebook_read_is_unpinned_subjective_data_and_audit_omits_its_content():
    actor = mind()
    draft = NotebookDraft(NotebookWorkspace(b'{"private":"unverified claim"}'))
    tools = Tools(actor, observation(), {}, notebook=draft)
    request = notebook_requests.NotebookRead(tool="notebook_read", path="/private")
    result = tools.execute(request)
    assert result["json_fragment"] == '"unverified claim"'
    assert tools.mind is actor and not tools.pins and not tools.exposed
    assert not tools.mind.sources and not tools.mind.snapshot.evidence
    audit = json.dumps({"request": request_summary(request), "result": result_summary(result)})
    assert "unverified claim" not in audit and "/private" not in audit
    assert draft.context()["meaning"] == "self_authored_subjective_notes_not_world_evidence"
