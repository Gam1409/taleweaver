"""A final possession or outfit cannot prove an invented action by a controlled NPC."""

import pytest

from backend.engine.npc_actions import custody_citations
from backend.engine.visual_novel.continuity import SCENE
from tests.conftest import TestSessionLocal
from tests.test_npc_completed_change_review import published
from tests.test_npc_custody_citations import RESOLUTION, action, review


@pytest.mark.parametrize(
    "basis,performer,expected",
    [
        ("completed", "LINA", True),
        ("completed", "UNRESOLVED_PERFORMER", True),
        ("completed", "SECOND", False),
        ("claim", "LINA", False),
        ("hypothetical", "LINA", False),
        ("attempt", "LINA", False),
    ],
)
async def test_own_completed_putdown_requires_an_operation_even_if_key_was_already_in_room(
    basis, performer, expected
):
    async with TestSessionLocal() as db:
        _, turn = await published(db, empty=True)
        turn.initial.settings.npc_decision_mode = "two_phase"
        text = "The visitors are talking. The key lies on the desk."
        evidence = action(
            text, source="LINA", destination=SCENE, basis=basis, performed_by=performer
        )
        proof = custody_citations.capture(turn, review(turn, text), text, RESOLUTION)
        issues = custody_citations.conflicts(proof, turn, text, RESOLUTION, [evidence])
        assert [row["reason_code"] for row in issues] == (
            ["unconfirmed_item_change"] if expected else []
        )
