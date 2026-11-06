"""Slow reflections require dated personal experience and remain reversible."""

from types import SimpleNamespace

import pytest

from backend.engine.chpm import development, lifecycle
from backend.engine.chpm import development_context as context
from backend.engine.chpm.core.contracts import Genesis
from backend.engine.chpm.core.reducer import initial
from backend.engine.chpm.core.replay import restore
from backend.engine.chpm.development_contracts import Development
from backend.engine.chpm.host_observation_contracts import HostFacts
from backend.engine.chpm.host_state import Mind, before_messages, record
from backend.engine.chpm.identity_adapter import from_actor
from backend.engine.chpm.schema import KernelState
from backend.engine.chpm.state import KEY
from tests.test_chpm_host_state import mind, source


def history(minutes=(1, 1441, 2881), scenes=("room", "room", "room"), speaker="npc"):
    base = mind()
    identity = from_actor(
        SimpleNamespace(
            id="npc",
            character="Independent engineer",
            goal="Protect the bridge",
            metadata_json={"personality_profile": {"trust": "cautious"}},
        )
    )
    genesis = Genesis(scope=base.genesis.scope, identity=identity)
    value = Mind(genesis=genesis, snapshot=initial(genesis))
    for number, (minute, scene) in enumerate(zip(minutes, scenes, strict=True)):
        frame = source(f"frame-{number}", kind="host_frame", text=scene).model_copy(
            update={"facts": HostFacts(scene_id=scene)}
        )
        value = record(value, frame, minute=minute)
        speech = source(
            f"speech-{number}", text=f"I checked the plan on occasion {number}."
        ).model_copy(
            update={"speaker_id": speaker, "role": "user" if speaker == "@player" else "assistant"}
        )
        value = record(value, speech, minute=minute)
    return value


def proposal(value, **changes):
    episodes = context.episodes(value)
    return Development.model_validate(
        {
            "category": "habit",
            "statement": "Tends to discuss the checks before agreeing here.",
            "citations": [
                {"episode_id": alias, "quote": item.excerpt}
                for alias, item in list(episodes.items())[:3]
            ],
            "alternatives": ["Only this work situation may explain the pattern"],
            "unknowns": ["Behavior elsewhere"],
            **changes,
        }
    )


def accept(value, entry, message="now"):
    return development.accept(value, [entry], context.episodes(value), message_id=message)


def test_habit_preserves_identity_retry_replay_and_source_retraction():
    value = history()
    entry = proposal(value)
    changed, ids = accept(value, entry)
    assert changed.genesis == value.genesis
    assert len(ids) == 1 and context.tendencies(changed)[0]["status"] == "tentative"
    assert accept(changed, entry)[0] == changed
    assert (
        restore(changed.snapshot.model_dump(), expected_genesis=value.genesis) == changed.snapshot
    )
    assert not before_messages(changed, {"speech-1"}).snapshot.beliefs
    assert not value.snapshot.beliefs
    with pytest.raises(ValueError, match="not new support"):
        accept(changed, entry, "retry-with-new-id")
    with pytest.raises(ValueError, match="rewording"):
        accept(changed, proposal(changed, statement="A convenient replacement claim"))


@pytest.mark.parametrize(
    "minutes,scenes,speaker,changes,match",
    [
        ((1, 2, 3), ("room",) * 3, "npc", {}, "minimum game-time"),
        ((1, 1441, 2881), ("room",) * 3, "@player", {}, "own reviewed speech"),
        ((1, 1441, 2881), ("room", "other", "room"), "npc", {}, "one observed scene"),
        (
            (1, 1441, 2881),
            ("room",) * 3,
            "npc",
            {"category": "trait", "trait_key": "trust"},
            "minimum game-time",
        ),
        (
            (1, 5041, 10081),
            ("room",) * 3,
            "npc",
            {"category": "trait", "trait_key": "trust"},
            "at least two",
        ),
        (
            (1, 5041, 10081),
            ("room", "other", "room"),
            "npc",
            {"category": "trait", "trait_key": "invented"},
            "authored trait",
        ),
        (
            (1, 1441, 2881),
            ("room",) * 3,
            "npc",
            {
                "category": "relationship",
                "about_id": "stranger",
                "relationship_domain": "reliability",
            },
            "speech from that subject",
        ),
    ],
)
def test_rejects_instant_changes_player_trait_commands_and_invalid_scope(
    minutes, scenes, speaker, changes, match
):
    value = history(minutes, scenes, speaker)
    before = value.model_dump_json()
    with pytest.raises(ValueError, match=match):
        accept(value, proposal(value, **changes))
    assert value.model_dump_json() == before


def test_trait_is_qualified_after_time_and_multiple_scenes_not_replaced():
    value = history((1, 5041, 10081), ("room", "other", "room"))
    changed, _ = accept(value, proposal(value, category="trait", trait_key="trust"))
    tendency = context.tendencies(changed)[0]
    assert tendency["kind"] == "trait" and tendency["qualifier"] == "trust"
    assert changed.genesis.identity.traits[0].value == "cautious"
    assert tendency["original_identity_changed"] is False


def test_counterexamples_stay_contested_and_habits_do_not_leak_between_scenes():
    value = history((1, 1441, 2881, 4321), ("room",) * 4)
    episodes = context.episodes(value)
    changed, ids = accept(
        value,
        proposal(value, counterexamples=[{"episode_id": "d4", "quote": episodes["d4"].excerpt}]),
    )
    assert len(ids) == 2 and context.tendencies(changed)[0]["status"] == "contested"
    elsewhere = record(
        changed,
        source("elsewhere", kind="host_frame", text="Elsewhere").model_copy(
            update={"facts": HostFacts(scene_id="elsewhere")}
        ),
        minute=5000,
    )
    assert context.tendencies(elsewhere) == []
    assert len(elsewhere.snapshot.beliefs) == 1


def test_fork_rebinds_development_sources_without_changing_identity():
    value = history()
    changed, _ = accept(value, proposal(value))
    mapping = {s.message_id: "copy-" + s.message_id for s in changed.sources.values()}
    copied = lifecycle.fork(
        {KEY: KernelState(minds={"npc": changed}).model_dump()}, mapping, "copy"
    )
    forked = KernelState.model_validate(copied[KEY]).minds["npc"]
    assert forked.genesis.identity == changed.genesis.identity
    assert context.tendencies(forked)[0]["tendency"] == context.tendencies(changed)[0]["tendency"]


def test_no_dated_frames_means_no_consolidation_and_sampling_preserves_endpoints():
    assert context.episodes(record(mind(), source(), minute=1)) == {}
    value = history(tuple(range(0, 40000, 1000)), ("room",) * 40)
    samples = list(context.episodes(value).values())
    assert len(samples) == 9
    assert samples[0].minute == 0 and samples[-1].minute == 39000


def test_optional_consolidation_defers_only_budget_errors(monkeypatch):
    from backend.engine.chpm import cognitive_context, development_request
    from backend.engine.chpm.kernel import ChpmError
    from backend.engine.chpm.schema import Settings
    from tests.test_chpm_kernel import observation

    calls = []

    def pack(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise cognitive_context.ContextBudgetError("Too large")
        return None, None, {}, {}

    monkeypatch.setattr(cognitive_context, "pack", pack)
    result = development_request.prepare(
        history(), observation(), {}, [], Settings(), "instruction"
    )
    assert result[-1] == "deferred_input_budget"
    assert calls[1]["extra"]["development_context"]["basis"] == []

    def broken(*args, **kwargs):
        raise ChpmError("Invalid source")

    monkeypatch.setattr(cognitive_context, "pack", broken)
    with pytest.raises(ChpmError, match="Invalid source"):
        development_request.prepare(history(), observation(), {}, [], Settings(), "instruction")
