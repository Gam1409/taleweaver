"""VN worlds intentionally omit sequences without becoming legacy adventures."""

import pytest

from backend.api.routes.adventures.logic import AdventureLogic
from backend.core.adventure_format import CURRENT_VERSION
from backend.engine.adventure_updates import (
    check_template_update,
    is_legacy_session,
    is_legacy_template,
)
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState


def template(mode, manifest):
    return AdventureTemplate(
        id="vn-format-world",
        title="A conversation",
        origin_id="imported-world",
        rule_enforcement_mode=mode,
        original_manifest=manifest,
        sequences=[],
    )


def snapshot_state(mode, manifest):
    return SessionState(
        id="vn-format-state",
        session_id="vn-format-session",
        entity_states={
            AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY: {
                "adventure": {"rule_enforcement_mode": mode},
                "original_manifest": manifest,
            }
        },
    )


@pytest.mark.parametrize(
    "manifest",
    [
        {"format_version": CURRENT_VERSION, "sequences": []},
        {"plot": "A new relationship", "sequences": []},
        {"format_version": CURRENT_VERSION, "version": "1.0", "sequences": []},
    ],
)
def test_current_or_unversioned_vn_accepts_empty_sequences(manifest):
    adventure = template("vn", manifest)
    state = snapshot_state("vn", manifest)
    assert is_legacy_template(adventure) is False
    assert is_legacy_session(template=adventure, state=state) is False
    assert is_legacy_session(state=state) is False
    status = check_template_update(adventure, [])
    assert status["can_start"] is True
    assert status["is_legacy_format"] is False
    assert status["has_sequences"] is False


@pytest.mark.parametrize("version_key", ["version", "format_version"])
def test_explicitly_old_vn_version_still_requires_migration(version_key):
    manifest = {version_key: "1.0", "sequences": []}
    adventure = template("vn", manifest)
    state = snapshot_state("vn", manifest)
    assert is_legacy_template(adventure) is True
    assert is_legacy_session(template=adventure, state=state) is True
    assert is_legacy_session(state=state) is True
    assert check_template_update(adventure, [])["can_start"] is False


@pytest.mark.parametrize("mode", ["rpg", "chat", None])
def test_other_modes_keep_existing_missing_sequence_detection(mode):
    manifest = {"format_version": CURRENT_VERSION, "sequences": []}
    assert is_legacy_template(template(mode, manifest)) is True
    assert is_legacy_session(state=snapshot_state(mode, manifest)) is True


def test_template_mode_is_authoritative_for_a_linked_session():
    manifest = {"format_version": CURRENT_VERSION, "sequences": []}
    adventure = template("vn", manifest)
    state = snapshot_state(None, manifest)
    assert is_legacy_session(template=adventure, state=state) is False


def test_vn_template_does_not_hide_an_explicit_old_session_snapshot():
    adventure = template("vn", {"format_version": CURRENT_VERSION, "sequences": []})
    state = snapshot_state("vn", {"format_version": "1.0", "sequences": []})
    assert is_legacy_session(template=adventure, state=state) is True
