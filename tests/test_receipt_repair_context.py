"""Receipt repair uses the rejected source occurrence once, scoped to its original review."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.engine.chpm import inference, receipt_review, rendering
from tests.conftest import TestSessionLocal
from tests.test_npc_completed_change_review import claim, published, reviewer

OLD = 'Lina: "Let me think."\nShe turned the key over, then set it down on the desk.'
NEW = 'Lina: "Let me think."\nThe brass caught the lamplight as she turned the key and laid it beside the ledger.'
UNKNOWN = "invented-private-receipt"


def suspect(tool="put_down_item", target="KEY"):
    return {
        "actor_id": "LINA",
        "passage_id": "p1",
        "operation_id": UNKNOWN,
        "tool": tool,
        "target_id": target,
    }


async def test_repair_and_second_review_receive_scoped_source_even_after_paraphrase(monkeypatch):
    async with TestSessionLocal() as db:
        manager, turn = await published(db, empty=True)
        first = reviewer(monkeypatch, [suspect()])
        assert not (await rendering._review(manager, turn, OLD, "")).matches
        repair = receipt_review.feedback(turn, OLD, "")["completed_change_rejections"]
        issue = repair["rejections"][0]
        assert issue["source_passage"] == first[0]["passages"]["p1"]
        assert issue["claimed_tool"] == "put_down_item" and issue["claimed_target_id"] == "KEY"
        assert issue["expected_public_result"] is None and UNKNOWN not in json.dumps(repair)
        assert receipt_review.feedback(turn, NEW, "") == {}
        assert receipt_review.feedback(turn, OLD, "another resolution") == {}

        seen = []

        async def negative(_system, payload, _model, **_kwargs):
            body = json.loads(payload)
            seen.append(body)
            return json.dumps(
                {
                    "matches": False,
                    "review_scope": body["review_scope"],
                    "rejections": [
                        {"reason_code": "world", "actor_id": "LINA", "passage_id": "p1"}
                    ],
                }
            )

        llm = SimpleNamespace(
            model="mock",
            max_tokens=8192,
            request_timeout=10,
            aexecute_simple_task=AsyncMock(side_effect=negative),
        )
        monkeypatch.setattr(inference, "model_for", lambda *_args: llm)
        assert not (await rendering._review(manager, turn, NEW, "", repaired_from=OLD)).matches
        assert seen[0]["passages"]["p1"] != issue["source_passage"]
        prior = seen[0]["previously_rejected_changes"]
        assert prior["source_review_scope"] == repair["review_scope"] != seen[0]["review_scope"]
        assert prior["rejections"] == repair["rejections"]
        assert not receipt_review.feedback(turn, OLD, "")
        assert turn.usage.calls == 2


async def test_corrected_public_receipt_and_direct_review_do_not_inherit_old_verdict(monkeypatch):
    async with TestSessionLocal() as db:
        manager, turn = await published(db)
        reviewer(monkeypatch, [suspect("private-invented-tool", "private-invented-target")])
        assert not (await rendering._review(manager, turn, OLD, "")).matches
        context = receipt_review.feedback(turn, OLD, "")
        assert "private-invented" not in json.dumps(context)
        valid = reviewer(monkeypatch, [claim(turn)])
        assert (await rendering._review(manager, turn, NEW, "", repaired_from=OLD)).matches
        assert valid[0]["previously_rejected_changes"]["rejections"]
        assert (await rendering._review(manager, turn, NEW, "")).matches
        assert "previously_rejected_changes" not in valid[1]


async def test_unrelated_review_cannot_recover_a_prior_scope(monkeypatch):
    async with TestSessionLocal() as db:
        manager, turn = await published(db, empty=True)
        reviewer(monkeypatch, [suspect()])
        assert not (await rendering._review(manager, turn, OLD, "")).matches
        # Identical wording with a new owner resolution belongs to a different binding.
        seen = reviewer(monkeypatch, [])
        assert (
            await rendering._review(manager, turn, NEW, "different resolution", repaired_from=OLD)
        ).matches
        assert "previously_rejected_changes" not in seen[0]


async def test_existing_prose_repair_forwards_source_once_and_accepts_corrected_citation(
    monkeypatch,
):
    async with TestSessionLocal() as db:
        manager, turn = await published(db)
        seen = []

        async def review(_system, raw, _model, **_kwargs):
            payload = json.loads(raw)
            seen.append(payload)
            return json.dumps(
                {
                    "review_scope": payload["review_scope"],
                    "matches": True,
                    "evidence": [{"actor_id": "LINA", "passage_id": "p0"}],
                    "actions": [{"actor_id": "LINA", "passage_id": "p1"}],
                    "completed_changes": [suspect("take_item") if len(seen) == 1 else claim(turn)],
                }
            )

        llm = SimpleNamespace(
            model="mock",
            max_tokens=8192,
            request_timeout=10,
            aexecute_simple_task=AsyncMock(side_effect=review),
        )
        monkeypatch.setattr(inference, "model_for", lambda *_args: llm)
        repaired = 'Lina: "Let me think."\nShe picks up the key.'

        async def repair(_manager, current, original, resolution, _issues, _system):
            assert (
                receipt_review.feedback(current, original, resolution)[
                    "completed_change_rejections"
                ]["rejections"][0]["source_passage"]
                == seen[0]["passages"]["p1"]
            )
            return repaired

        monkeypatch.setattr(rendering, "_repair", repair)
        assert await rendering._validated(manager, turn, OLD, "", "", None, "") == repaired
        assert len(seen) == 2 and "previously_rejected_changes" not in seen[0]
        assert (
            seen[1]["previously_rejected_changes"]["source_review_scope"] == seen[0]["review_scope"]
        )
        assert turn.verdict.matches and not turn.review_change_feedback
