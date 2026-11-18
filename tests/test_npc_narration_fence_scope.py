"""Late observation checks require current host publication and exact source binding."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.core.text_evidence import EvidenceSpan
from backend.engine import turn_controls
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.engine.narrated_items.schema import ItemAction
from backend.engine.npc_actions import narration_fence
from backend.engine.npc_actions.control import CommandRejectedError
from tests.test_npc_action_previews import fixture

TEXT = "The actor currently holds the key."


def captured():
    host, scope, draft = fixture()
    settings = Settings(
        mode="live", workflow="integrated", actor_ids=["npc"], action_tools=True, agent_steps=2
    )
    host.state.entity_states = {
        **host.state.entity_states,
        KEY: KernelState(settings=settings).model_dump(),
    }
    draft.approved = True
    draft.published_results = []
    host._chpm_turn = SimpleNamespace(
        initial=KernelState(settings=settings),
        input_id=scope.input_id,
        control=turn_controls.scope(host, "narration_review", observation=scope.observation),
        action_outcomes={"npc": []},
        action_drafts={"npc": draft},
    )
    return host, draft


def claim(**changes):
    return ItemAction.model_validate(
        {
            "item_id": "KEY",
            "source_owner": "npc",
            "destination_owner": "npc",
            "disposition": "held",
            "basis": "observed_possession",
            "evidence": TEXT,
            "evidence_span": {"start": 0, "end": len(TEXT)},
            **changes,
        }
    )


@pytest.mark.parametrize(
    "kind",
    [
        "unapproved",
        "unpublished",
        "foreign_actor",
        "foreign_input",
        "foreign_revision",
        "foreign_hash",
        "foreign_scene",
        "foreign_session",
    ],
)
def test_ineligible_publication_cannot_supply_a_late_fence(kind):
    host, draft = captured()
    if kind == "unapproved":
        draft.approved = False
    elif kind == "unpublished":
        draft.published_results = None
    else:
        field = {
            "foreign_actor": "actor_id",
            "foreign_input": "input_id",
            "foreign_revision": "input_revision",
            "foreign_hash": "input_hash",
            "foreign_scene": "scene_id",
            "foreign_session": "session_id",
        }[kind]
        draft.scope = replace(draft.scope, **{field: "foreign"})
    narration_fence.begin(host, TEXT)
    assert host._npc_narration_fence is None


def test_approved_empty_owner_publication_is_a_real_control_boundary():
    host, _ = captured()
    narration_fence.begin(host, TEXT)
    check = host._npc_narration_fence
    assert isinstance(check, narration_fence.Check)
    assert set(check.publications) == {"npc"}
    narration_fence.items(host, [claim()])
    assert check.items == [claim()]


@pytest.mark.parametrize(
    "kind",
    ["missing_span", "wrong_span", "foreign_actor", "intermediate", "uncertain", "foreign_attempt"],
)
def test_source_free_foreign_or_nonfinal_claims_do_not_become_fence_evidence(kind):
    host, _ = captured()
    narration_fence.begin(host, TEXT)
    changes = {
        "missing_span": {"evidence_span": None},
        "wrong_span": {"evidence_span": EvidenceSpan(start=1, end=len(TEXT))},
        "foreign_actor": {"source_owner": "other", "destination_owner": "other"},
        "intermediate": {"basis": "completed", "source_owner": "__scene__"},
        "uncertain": {"basis": "uncertain"},
        "foreign_attempt": {},
    }
    check = host._npc_narration_fence
    if kind == "foreign_attempt":
        turn_controls.begin(host)
    narration_fence.items(host, [claim(**changes[kind])])
    assert check.items == []


@pytest.mark.parametrize("kind", ["withdrawn", "different_narration", "different_input"])
async def test_enforcement_cannot_reuse_withdrawn_or_changed_source_claims(kind):
    host, draft = captured()
    narration_fence.begin(host, TEXT)
    narration_fence.items(host, [claim()])
    if kind == "withdrawn":
        draft.approved = False
    if kind == "different_input":
        host._turn_control_input = {**host._turn_control_input, "input_revision": "changed"}
    await narration_fence.enforce(
        host, TEXT + " Changed." if kind == "different_narration" else TEXT
    )
    assert host._npc_narration_fence is None


def test_a_forged_nonempty_publication_still_fails_its_existing_owner_guard():
    host, draft = captured()
    fake = {"status": "applied", "effect": {"item_id": "KEY", "destination_owner": "npc"}}
    draft.published_results = [fake]
    host._chpm_turn.action_outcomes = {"npc": [fake]}
    with pytest.raises(CommandRejectedError, match="operation record"):
        narration_fence.begin(host, TEXT)
