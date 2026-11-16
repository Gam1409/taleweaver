"""Detached sessions retain canonical chapter definitions and legacy fallbacks."""

from copy import deepcopy

import pytest

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.gameplay.world import AdventureLogic
from backend.models import AdventureTemplate, User
from tests.test_session_progress_portability import SEQUENCES, _context, progress_db

__all__ = ["progress_db"]


def _sequences():
    sequences = deepcopy(SEQUENCES)
    sequences[1]["required_scene_id"] = "MIDDLE_END"
    sequences[2]["required_scene_id"] = "FINAL_END"
    return sequences


async def _detach(db, source):
    template = await db.get(AdventureTemplate, "template")
    definitions = _sequences()
    template.original_manifest = {"sequences": deepcopy(definitions)}
    if source == "edited":
        definitions[1]["exp_reward"] = 70
    if source == "cleared":
        definitions = []
    template.sequences = definitions
    snapshot = AdventureLogic.build_session_manifest_snapshot(template)
    if source.startswith("legacy"):
        snapshot["adventure"].pop("sequences", None)
    if source == "legacy-malformed":
        snapshot["original_manifest"]["sequences"] = {"invalid": "not a list"}
    _, state, _ = await _context(db)
    state.entity_states = {AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY: snapshot}
    await db.commit()
    await AdventureLogic.delete_adventure(db, "template")
    db.expunge_all()
    return [] if source == "legacy-malformed" else definitions


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["canonical", "legacy", "edited", "cleared", "legacy-malformed"])
async def test_detached_manager_retains_chapters_and_awards_the_next_reward_once(
    progress_db, source
):
    db = progress_db
    expected = await _detach(db, source)
    game, state, avatar = await _context(db)
    assert game.template_id is None
    assert (state.active_sequence_id, state.active_sequence_order, avatar.exp) == ("CH2", 20, 250)
    manager = GameTurnManager(db, "source", await db.get(User, "owner"))
    assert await manager.initialize()
    assert manager.adventure.sequences == expected
    messages = AdventureLogic.evaluate_sequence_progress(
        manager.adventure, manager.state, manager.avatar, new_scene_id="MIDDLE_END"
    )
    if not expected:
        assert messages == []
        assert manager.avatar.exp == 250
        return
    reward = 70 if source == "edited" else 20
    assert messages == [
        f"Sequence completed: Second chapter (+{reward} XP)",
        "New Sequence unlocked: Third chapter",
    ]
    assert (
        AdventureLogic.evaluate_sequence_progress(
            manager.adventure, manager.state, manager.avatar, new_scene_id="MIDDLE_END"
        )
        == []
    )
    await db.commit()
    db.expunge_all()
    _, state, avatar = await _context(db)
    assert (state.active_sequence_id, state.active_sequence_order, avatar.exp) == (
        "CH3",
        30,
        250 + reward,
    )


@pytest.mark.asyncio
async def test_session_snapshot_copies_current_chapter_definitions_independently(progress_db):
    template = await progress_db.get(AdventureTemplate, "template")
    definitions = _sequences()
    template.sequences = deepcopy(definitions)
    snapshot = AdventureLogic.build_session_manifest_snapshot(template)
    assert snapshot["adventure"].get("sequences") == definitions
    template.sequences[1]["exp_reward"] = 999
    assert snapshot["adventure"]["sequences"] == definitions
    snapshot["adventure"]["sequences"][1]["title"] = "Snapshot-only edit"
    assert template.sequences[1]["title"] == "Second chapter"


@pytest.mark.asyncio
async def test_detached_definition_copy_does_not_mutate_the_saved_manifest(progress_db):
    await _detach(progress_db, "legacy")
    manager = GameTurnManager(progress_db, "source", await progress_db.get(User, "owner"))
    assert await manager.initialize()
    assert manager.adventure.sequences == _sequences()
    manager.adventure.sequences[1]["exp_reward"] = 999
    snapshot = AdventureLogic.extract_manifest_snapshot(manager.state)
    assert snapshot["original_manifest"]["sequences"][1]["exp_reward"] == 20
