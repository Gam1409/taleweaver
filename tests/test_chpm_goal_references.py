"""Observe-mode goal references preserve supported source lengths and canonical quotes."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.engine.chpm import cognition
from backend.engine.chpm.inference import InvalidResponseError
from backend.engine.chpm.kernel import ChpmError, fingerprint
from backend.engine.chpm.schema import Decision, Settings, Usage
from tests.test_chpm_kernel import observation


class GoalModel:
    model = "offline-goal-reference"
    max_tokens = 4096
    request_timeout = 1

    def __init__(self, *, edit=None, alignment="supports"):
        self.requests = []
        self.edit = edit
        self.alignment = alignment

    async def aexecute_simple_task(self, system, content, _model, **_kwargs):
        payload = json.loads(content)
        self.requests.append((system, payload))
        fragments = payload.get("authored_goal_fragments")
        reference = next(reversed(fragments)) if fragments else "authored_goal"
        response = {
            "reference_scope": payload["reference_scope"],
            "appraisal": "Act on the authored goal.",
            "candidates": {
                "CONTINUE": {
                    "intention": "Work toward the authored goal.",
                    "goal_alignment": self.alignment,
                    "goal_ref": reference if self.alignment in {"supports", "conflicts"} else None,
                    "reconsider_if": "The goal is already fulfilled.",
                    "agenda_change": None,
                },
                "DEFER": {
                    "intention": "Remain silent.",
                    "goal_alignment": "unknown",
                    "goal_ref": None,
                    "reconsider_if": "New information arrives.",
                    "agenda_change": None,
                },
            },
        }
        if self.edit is not None:
            self.edit(response)
        return json.dumps(response)


async def decide(goal, *, model=None):
    model = model or GoalModel()
    host = SimpleNamespace(game_id="session", _chpm_model_factory=lambda _role: model)
    supplied = {"authored_goal": goal}
    before = deepcopy(supplied)
    usage = Usage()
    result = await cognition.decide(
        host,
        Settings(mode="shadow", actor_ids=["npc"]),
        usage,
        "npc",
        observation(),
        supplied,
        [],
    )
    assert supplied == before
    assert result.context_hash == fingerprint(supplied)
    assert usage.calls == 1 and usage.proposal_repairs == 0
    assert Decision.model_validate_json(result.model_dump_json()) == result
    assert "goal_ref" not in result.model_dump_json()
    return result, model.requests[0]


@pytest.mark.parametrize("length", [300, 301, 1000])
async def test_long_authored_goals_keep_grounded_alignment_without_changing_quote_limits(length):
    goal = "Keep the bridge safe. " + "x" * (length - 22)
    result, (_system, payload) = await decide(goal)
    assert result.selected.kind == "CONTINUE"
    assert result.selected.goal_alignment == "supports"
    quote = result.selected.goal_quote
    assert 0 < len(quote) <= 300 and quote in goal
    if length <= 300:
        assert payload["authored_goal"] == goal
        assert "authored_goal_fragments" not in payload
        assert quote == goal
    else:
        fragments = payload["authored_goal_fragments"]
        assert "authored_goal" not in payload
        assert len(fragments) <= (length + 299) // 300
        assert all(0 < len(text) <= 300 and text in goal for text in fragments.values())
        assert "".join("".join(fragments.values()).split()) == "".join(goal.split())
        assert quote == list(fragments.values())[-1]


@pytest.mark.parametrize("index", range(4))
async def test_each_long_goal_excerpt_materializes_only_its_exact_source(index):
    goal = "A" * 300 + "B" * 300 + "C" * 300 + "D" * 100

    def edit(response):
        response["candidates"]["CONTINUE"]["goal_ref"] = f"authored_goal_{index}"

    result, _request = await decide(goal, model=GoalModel(edit=edit))
    assert result.selected.goal_quote == goal[index * 300 : (index + 1) * 300]


@pytest.mark.parametrize(
    "goal",
    ["Protect the bridge.\n" * 40, "守る。" * 200, "  " + "x" * 600 + "  "],
)
async def test_dense_and_unicode_goals_remain_complete_with_bounded_reference_count(goal):
    result, (_system, payload) = await decide(goal)
    fragments = payload["authored_goal_fragments"]
    assert len(fragments) <= (len(goal) + 299) // 300
    assert "".join("".join(fragments.values()).split()) == "".join(goal.split())
    assert all(0 < len(text) <= 300 and text in goal for text in fragments.values())
    assert result.selected.goal_quote in goal


@pytest.mark.parametrize(
    "reference", ["authored_goal", "authored_goal_4", " authored_goal_0 ", "foreign"]
)
async def test_unoffered_long_goal_handles_never_become_canonical_grounding(reference):
    def edit(response):
        response["candidates"]["CONTINUE"]["goal_ref"] = reference

    model = GoalModel(edit=edit)
    with pytest.raises(InvalidResponseError, match="goal_ref selects an unavailable"):
        await decide("x" * 1000, model=model)
    assert len(model.requests) == 1


async def test_a_long_goal_handle_is_unavailable_for_the_legacy_short_goal():
    def edit(response):
        response["candidates"]["CONTINUE"]["goal_ref"] = "authored_goal_0"

    with pytest.raises(InvalidResponseError, match="goal_ref selects an unavailable"):
        await decide("Protect the bridge.", model=GoalModel(edit=edit))


async def test_another_goal_or_attempt_cannot_reuse_an_old_reference_scope():
    _first, (_system, previous) = await decide("a" * 301)

    def edit(response):
        response["reference_scope"] = previous["reference_scope"]

    model = GoalModel(edit=edit)
    with pytest.raises(InvalidResponseError, match="reference_scope selects an unavailable"):
        await decide("b" * 301, model=model)
    assert len(model.requests) == 1


@pytest.mark.parametrize("goal", ["", "   ", "Protect the bridge.", "x" * 1000])
@pytest.mark.parametrize("alignment", ["neutral", "unknown"])
async def test_neutral_or_unknown_alignment_needs_no_goal_quote(goal, alignment):
    result, _request = await decide(goal, model=GoalModel(alignment=alignment))
    assert all(not candidate.goal_quote for candidate in result.proposal.candidates)


async def test_long_goal_cache_and_source_change_checks_use_the_unchanged_full_source():
    model = GoalModel()
    host = SimpleNamespace(game_id="session", _chpm_model_factory=lambda _role: model)
    settings = Settings(mode="shadow", actor_ids=["npc"])
    observed, supplied, usage = observation(), {"authored_goal": "x" * 1000}, Usage()
    first = await cognition.decide(host, settings, usage, "npc", observed, supplied, [])
    same = await cognition.decide(host, settings, usage, "npc", observed, supplied, [], first)
    assert same == first and len(model.requests) == usage.calls == 1
    with pytest.raises(ChpmError, match="source changed"):
        await cognition.decide(
            host, settings, usage, "npc", observed, {"authored_goal": "y" * 1000}, [], first
        )
    assert len(model.requests) == usage.calls == 1
