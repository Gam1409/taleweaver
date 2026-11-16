"""Controller selection reads settings without replaying every NPC's event ledger."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.engine.chpm import host_state, state
from backend.engine.chpm.schema import KernelState, Settings
from tests.test_chpm_host_state import mind


def fixture():
    value = mind()
    actor = value.genesis.scope.observer_id
    raw = KernelState(
        settings=Settings(mode="live", actor_ids=[actor]), minds={actor: value}
    ).model_dump(mode="json")
    return SimpleNamespace(entity_states={state.KEY: raw}), actor


def test_selection_does_not_replay_the_same_ledger_for_each_candidate(monkeypatch):
    session, actor = fixture()
    replay = Mock(wraps=host_state.restore)
    monkeypatch.setattr(host_state, "restore", replay)
    before = deepcopy(session.entity_states)
    for _ in range(20):
        assert state.controls(session, actor)
        assert not state.controls(session, "unselected")
    assert replay.call_count == 0
    assert session.entity_states == before
    state.load(session)
    assert replay.call_count > 0  # Full admission still validates the ledger.


def test_selection_immediately_observes_setting_changes_without_a_stale_cache():
    session, actor = fixture()
    assert state.controls(session, actor)
    session.entity_states[state.KEY]["settings"]["mode"] = "off"
    assert not state.controls(session, actor)
    session.entity_states[state.KEY]["settings"]["mode"] = "live"
    session.entity_states[state.KEY]["settings"]["actor_ids"] = ["another"]
    assert not state.controls(session, actor) and state.controls(session, "another")


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 6])
def test_lightweight_selection_accepts_supported_envelope_versions(version):
    session, actor = fixture()
    session.entity_states[state.KEY]["schema_version"] = version
    assert state.controls(session, actor)


def test_lightweight_selection_still_refuses_unsupported_versions_and_bad_settings():
    session, actor = fixture()
    session.entity_states[state.KEY]["schema_version"] = 999
    with pytest.raises(ValueError):
        state.controls(session, actor)
    session.entity_states[state.KEY]["schema_version"] = 6
    session.entity_states[state.KEY]["settings"]["mode"] = "unsupported"
    with pytest.raises(ValueError):
        state.controls(session, actor)
