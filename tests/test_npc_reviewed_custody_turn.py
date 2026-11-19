"""Cross-check a reviewer's passage/receipt against independently extracted custody."""

import json

import pytest
from sqlalchemy import select

from backend.engine.chpm.state import load
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.turn_replay import drafts
from backend.engine.visual_novel.continuity import SCENE
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import LocalFailureRoles, install
from tests.test_npc_two_phase_turn import CUP, PLAYER, TAKE, CupRoles, reload, seed

SPEECH = "Лина: «Посылку открывать не буду.»"
DROP = "Лина ставит медную кружку на стол."
DROP_AGAIN = "Лина выпускает медную кружку из рук на стол."
PICK_UP = "Лина поднимает медную кружку со стола."


class CustodyRoles(CupRoles):
    def __init__(self, repaired_line, *, earlier_rejection=False):
        super().__init__([TAKE])
        self.repaired_line = repaired_line
        self.reject_reviews = int(earlier_rejection)
        self.repairs, self.reviewed_claims, self.extracted = [], [], []

    @property
    def story(self):
        return f"{SPEECH}\n{DROP if self.repaired_line else PICK_UP}"

    async def simple(self, system, payload, model, **kwargs):
        if kwargs.get("phase") == "repair":
            assert self.repaired_line, "An accurate custody echo needs no narration correction."
            self.repairs.append(json.loads(payload))
            return f"{SPEECH}\n{self.repaired_line}"
        return await super().simple(system, payload, model, **kwargs)

    def review(self, supplied):
        verdict = json.loads(super().review(supplied))
        if verdict["matches"]:
            (outcome,) = supplied["contract"]["LINA"]["authoritative_command_outcomes"]
            assert outcome["status"] == "applied" and outcome["tool"] == "take_item"
            passages = supplied["passages"]
            passage = next(
                key for key, line in passages.items() if line in {DROP, DROP_AGAIN, PICK_UP}
            )
            claim = {
                "actor_id": "LINA",
                "passage_id": passage,
                "operation_id": outcome["operation_id"],
                "tool": "take_item",
                "target_id": CUP,
            }
            verdict["actions"] = [{"actor_id": "LINA", "passage_id": passage}]
            verdict["completed_changes"] = [claim]
            self.reviewed_claims.append((claim, passages[passage]))
        return json.dumps(verdict)

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if not issubclass(schema, ItemExtraction):
            return await super().structured(*args, **kwargs)
        passages = json.loads(args[1])["completed_narration"]
        reference, line = next(
            (ref, text) for ref, text in passages.items() if text in {DROP, DROP_AGAIN, PICK_UP}
        )
        self.extracted.append(line)
        # This provider interprets the prose independently of the receipt reviewer.
        source, destination = (SCENE, "LINA") if line == PICK_UP else ("LINA", SCENE)
        return extraction(
            schema,
            actions=[
                {
                    "item_id": CUP,
                    "source_owner": source,
                    "destination_owner": destination,
                    "disposition": "held" if line == PICK_UP else "carried",
                    "basis": "completed",
                    "evidence": reference,
                }
            ],
        )


@pytest.mark.parametrize(
    "repaired_line,earlier_rejection",
    [(None, False), (PICK_UP, False), (DROP_AGAIN, False), (DROP_AGAIN, True)],
    ids=[
        "accurate-on-first-pass",
        "corrected",
        "still-contradictory",
        "shared-correction-already-used",
    ],
)
async def test_checked_custody_uses_one_buffered_correction_and_one_operation(
    monkeypatch, repaired_line, earlier_rejection
):
    roles = CustodyRoles(repaired_line, earlier_rejection=earlier_rejection)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, "json", pair=False)
        user_id, session_id = user.id, state.session_id
        _, events = await run(db, user, PLAYER)
        assert len(roles.choices) == len(roles.executions) == 1
        assert len(roles.repairs) == int(repaired_line is not None), (roles.extracted, events)
        assert len(roles.reviews) == 1 + len(roles.repairs)
        assert len({review["review_scope"] for review in roles.reviews}) == len(roles.reviews)
        lines = ([DROP] if repaired_line and not earlier_rejection else []) + [
            repaired_line or PICK_UP
        ]
        assert roles.extracted == lines
        assert [text for _, text in roles.reviewed_claims] == lines
        operation_ids = {claim["operation_id"] for claim, _ in roles.reviewed_claims}
        assert len(operation_ids) == 1
        if repaired_line and not earlier_rejection:
            feedback = roles.repairs[0]["completed_change_rejections"]
            assert feedback["review_scope"] == roles.reviews[0]["review_scope"]
            (failure,) = feedback["rejections"]
            assert failure["reason_code"] == "custody_direction_mismatch"
            assert failure["operation_id"] in operation_ids
            assert failure["passage_id"] == roles.reviewed_claims[0][0]["passage_id"]
            assert failure["expected_public_result"]["source_owner"] == SCENE
            assert failure["expected_public_result"]["destination_owner"] == "LINA"

    async with TestSessionLocal() as db:
        _, manager, snapshot = await reload(db, session_id, user_id)
        replies = list(
            await db.scalars(
                select(ChatMessage.content).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.content.contains(SPEECH),
                )
            )
        )
        chunks = [
            json.loads(row.partition("\ndata: ")[2])["content"]
            for row in events
            if row.startswith("event: chunk")
        ]
        success = repaired_line in {None, PICK_UP}
        assert any(row.startswith("event: final") for row in events) == success
        assert any(row.startswith("event: error") for row in events) != success
        assert snapshot.owners[CUP] == ("LINA" if success else SCENE)
        if success:
            assert chunks == replies == [f"{SPEECH}\n{PICK_UP}"]
            ack = load(manager.state).actors["LINA"].last_publication
            assert [row.operation_id for row in ack.operations] == list(operation_ids)
        else:
            assert chunks == replies == []
            assert not load(manager.state).actors
            assert drafts.KEY not in manager.state.entity_states


class UnconfirmedCorrection(CustodyRoles):
    def __init__(self, issue):
        super().__init__(DROP if issue == "omitted_claim" else PICK_UP)
        self.issue = issue

    async def simple(self, system, payload, model, **kwargs):
        reply = await super().simple(system, payload, model, **kwargs)
        if kwargs.get("phase") == "repair" and self.issue == "omitted_claim":
            return "Часы в коридоре пробили полдень.\n" + reply
        return reply

    def review(self, supplied):
        if self.reviews and self.issue == "omitted_claim":
            verdict = json.loads(LocalFailureRoles.review(self, supplied))
            return json.dumps({**verdict, "completed_changes": []})
        return super().review(supplied)

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if self.extracted and issubclass(schema, ItemExtraction) and self.issue != "omitted_claim":
            assert PICK_UP in json.loads(args[1])["completed_narration"].values()
            self.extracted.append(PICK_UP)
            if self.issue == "unavailable":
                raise TimeoutError("Extractor unavailable on corrected prose")
            # Omission and an explicit answer that nothing changed have separate semantics.
            return schema.model_validate(
                extraction(schema).model_dump(exclude_unset=True, exclude={"actions"})
            )
        return await super().structured(*args, **kwargs)


@pytest.mark.parametrize("issue", ["unavailable", "omitted_actions", "omitted_claim"])
async def test_unconfirmed_correction_never_becomes_an_interrupted_visible_draft(
    monkeypatch, issue
):
    roles = UnconfirmedCorrection(issue)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, "json", pair=False)
        user_id, session_id = user.id, state.session_id
        _, events = await run(db, user, PLAYER)
        assert len(roles.choices) == len(roles.executions) == len(roles.repairs) == 1
        assert len(roles.reviews) == 2
        assert roles.extracted == [DROP, roles.repaired_line]
        if issue == "omitted_claim":
            assert len(roles.reviewed_claims) == 1
            assert roles.reviews[0]["review_scope"] != roles.reviews[1]["review_scope"]
        assert any(row.startswith("event: error") for row in events)
        assert not any(row.startswith(("event: final", "event: chunk")) for row in events)

    async with TestSessionLocal() as db:
        _, manager, snapshot = await reload(db, session_id, user_id)
        assert snapshot.owners[CUP] == SCENE
        assert not load(manager.state).actors
        assert drafts.KEY not in manager.state.entity_states
        saved = await db.scalar(
            select(ChatMessage.id).where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == "assistant",
                ChatMessage.content.contains(SPEECH),
            )
        )
        assert saved is None
