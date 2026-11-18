"""Source-time ownership shares the reply envelope without creating catch-up work."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm.kernel import digest
from backend.engine.chpm.recovery_contracts import RecoveryAudit
from backend.engine.chpm.recovery_queue import stamp as stamp_recovery
from backend.engine.npc_actions import source_control

TEXT = "Lina adjusts the sleeves of her existing coat."


def message(**changes):
    return SimpleNamespace(
        **{
            "id": "reply",
            "session_id": "session",
            "role": "assistant",
            "revision_id": "revision",
            "scene_id": "room",
            "content": TEXT,
            "npc_recovery": None,
            "is_debug": False,
            **changes,
        }
    )


def host():
    return SimpleNamespace(
        game_id="session", state=SimpleNamespace(in_game_time=5, entity_states={})
    )


def current(outcomes=None, **changes):
    return SimpleNamespace(
        action_outcomes=outcomes if outcomes is not None else {"LINA": []},
        fallback_identities={},
        present_names={"LINA": "Lina"},
        **changes,
    )


def marked():
    reply = message()
    source_control.stamp(host(), current(), reply)
    return reply


def test_normal_explicit_empty_publication_marks_only_its_actor_and_has_no_catchup_cursor():
    reply = message()
    turn = current()
    turn.initial = SimpleNamespace(settings=SimpleNamespace(actor_ids=["LINA", "OTHER"]))
    source_control.stamp(host(), turn, reply)
    assert reply.npc_recovery["command_controlled_actor_ids"] == ["LINA"]
    assert reply.npc_recovery["actors"] == {}
    assert source_control.read(reply).actor_ids == {"LINA"}


@pytest.mark.parametrize("fallback", [False, True])
def test_no_published_control_keeps_ordinary_or_fallback_recovery(fallback):
    reply = message()
    turn = current({})
    if fallback:
        turn.fallback_identities = {"LINA": {}}
        stamp_recovery(host(), turn, reply)
    before = deepcopy(reply.npc_recovery)
    source_control.stamp(host(), turn, reply)
    assert reply.npc_recovery == before
    assert source_control.read(reply) == source_control.Snapshot()


def test_published_control_keeps_existing_fallback_cursors():
    reply = message()
    turn = current()
    turn.fallback_identities = {"LINA": {}, "SECOND": {}}
    stamp_recovery(host(), turn, reply)
    reply.npc_recovery["actors"]["LINA"] = 3
    source_control.stamp(host(), turn, reply)
    assert reply.npc_recovery["actors"] == {"LINA": 3, "SECOND": 0}
    assert source_control.read(reply).actor_ids == {"LINA"}


def test_legacy_audit_loading_and_serialization_have_no_new_authority_claim():
    legacy = {
        "content_hash": digest(TEXT),
        "revision_id": "revision",
        "scene_id": "room",
        "actors": {"LINA": 0},
    }
    audit = RecoveryAudit.model_validate(legacy)
    assert audit.command_controlled_actor_ids is None
    assert "command_controlled_actor_ids" not in audit.model_dump()
    assert source_control.read(message(npc_recovery=legacy)) == source_control.Snapshot()


@pytest.mark.parametrize(
    "change",
    [
        {"command_controlled_actor_ids": "LINA"},
        {"command_controlled_actor_ids": [""]},
        {"command_controlled_actor_ids": ["LINA"] * 21},
        {"content_hash": "a" * 64},
        {"revision_id": "another-revision"},
        {"scene_id": "another-room"},
    ],
)
def test_malformed_or_stale_present_authority_never_falls_back_to_legacy(change):
    reply = marked()
    reply.npc_recovery.update(change)
    snapshot = source_control.read(reply)
    assert not snapshot.valid and snapshot.signature != "legacy"


def test_independent_cursor_progress_does_not_change_source_time_command_ownership():
    reply = marked()
    before = source_control.read(reply)
    reply.npc_recovery["actors"] = {"OTHER": 2}
    assert source_control.read(reply) == before
    reply.npc_recovery.pop("command_controlled_actor_ids")
    assert source_control.read(reply) != before


@pytest.mark.parametrize("count", [20, 21])
def test_existing_actor_bound_is_enforced_without_silent_truncation(count):
    reply = message()
    turn = current({f"NPC_{index}": [] for index in range(count)})
    if count == 21:
        with pytest.raises(ValueError):
            source_control.stamp(host(), turn, reply)
        assert reply.npc_recovery is None
        return
    source_control.stamp(host(), turn, reply)
    assert len(source_control.read(reply).actor_ids) == count


@pytest.mark.parametrize("change", [{"role": "user"}, {"is_debug": True}, {"session_id": "other"}])
def test_noncanonical_reply_cannot_gain_command_source_authority(change):
    reply = message(**change)
    with pytest.raises(ValueError):
        source_control.stamp(host(), current(), reply)
    assert reply.npc_recovery is None
