"""A reviewer cannot hide an extracted custody contradiction by omitting its claims."""

import json

import pytest
from sqlalchemy import select

from backend.engine.chpm.state import load
from backend.engine.turn_replay import drafts
from backend.engine.visual_novel.continuity import SCENE
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import install
from tests.test_npc_reviewed_custody_turn import DROP, DROP_AGAIN, PICK_UP, SPEECH, CustodyRoles
from tests.test_npc_two_phase_turn import CUP, PLAYER, reload, seed


class EmptyFirstReview(CustodyRoles):
    def __init__(self, repaired_line, *, always_empty=False):
        super().__init__(repaired_line)
        self.always_empty = always_empty

    def review(self, supplied):
        verdict = json.loads(super().review(supplied))
        if len(self.reviews) == 1 or self.always_empty:
            verdict["completed_changes"] = []
        return json.dumps(verdict)


@pytest.mark.parametrize("protocol", ["native", "json"])
@pytest.mark.parametrize("always_empty", [False, True])
@pytest.mark.parametrize("repaired_line", [PICK_UP, DROP_AGAIN])
async def test_empty_first_claims_still_repair_or_rollback_before_emitting_a_reverse_transfer(
    monkeypatch, protocol, always_empty, repaired_line
):
    roles = EmptyFirstReview(repaired_line, always_empty=always_empty)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, protocol, pair=False)
        user_id, session_id = user.id, state.session_id
        _, events = await run(db, user, PLAYER)
        assert len(roles.choices) == len(roles.executions) == len(roles.repairs) == 1
        assert roles.extracted == [DROP, repaired_line]
        assert len(roles.reviews) == 2
        (failure,) = roles.repairs[0]["completed_change_rejections"]["rejections"]
        assert failure["reason_code"] == "custody_direction_mismatch"
        assert failure["expected_public_result"]["source_owner"] == SCENE
        assert failure["expected_public_result"]["destination_owner"] == "LINA"
        chunks = [
            json.loads(row.partition("\ndata: ")[2])["content"]
            for row in events
            if row.startswith("event: chunk")
        ]
        success = repaired_line == PICK_UP
        assert any(row.startswith("event: final") for row in events) == success
        assert any(row.startswith("event: error") for row in events) != success
        assert chunks == ([f"{SPEECH}\n{PICK_UP}"] if success else [])

    async with TestSessionLocal() as db:
        _, manager, snapshot = await reload(db, session_id, user_id)
        assert snapshot.owners[CUP] == ("LINA" if success else SCENE)
        saved = list(
            await db.scalars(
                select(ChatMessage.content).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.content.contains(SPEECH),
                )
            )
        )
        assert saved == chunks
        if success:
            publication = load(manager.state).actors["LINA"].last_publication
            assert len(publication.operations) == 1
        else:
            assert not load(manager.state).actors
            assert drafts.KEY not in manager.state.entity_states


@pytest.mark.parametrize("protocol", ["native", "json"])
async def test_accurate_take_with_empty_claims_needs_no_extra_model_calls(monkeypatch, protocol):
    roles = EmptyFirstReview(None, always_empty=True)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, protocol, pair=False)
        _, events = await run(db, user, PLAYER)
        assert len(roles.choices) == len(roles.executions) == len(roles.reviews) == 1
        assert not roles.repairs and roles.extracted == [PICK_UP]
        assert any(row.startswith("event: final") for row in events), "".join(events)
