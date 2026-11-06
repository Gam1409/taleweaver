"""Sequential fixture tests stay offline; no synthetic outcome becomes a world write."""

from backend.engine.chpm.evaluation.trajectory import Trajectory
from backend.engine.chpm.evaluation.trajectory_cases import STEPS
from backend.engine.chpm.identity_adapter import from_actor
from backend.engine.chpm.state import load
from tests.test_chpm_evaluation import Models, settings


async def test_accepted_decisions_and_sources_carry_forward_without_reauthoring_identity():
    models = Models()
    simulation = Trajectory(models, settings())
    identity = from_actor(simulation.actor)
    first = await simulation.step(1, STEPS[0])
    second = await simulation.step(2, STEPS[1])
    assert first["status"] == second["status"] == "ok"
    assert second["state_before"] == first["state_after"]
    assert len(simulation.history) == 4 and len(simulation.sources) == 4
    assert load(simulation.host.state).revision == 2
    assert from_actor(simulation.actor) == identity
    assert len(identity.traits) == 7 and identity.trait_model == "authored-categorical-v1"
    assert first["identity_hash_before"] == second["identity_hash_after"]
    proposals = [payload for phase, _, payload in models.requests if phase == "proposal"]
    remembered = proposals[1]["witnessed_utterances_not_world_facts"]
    assert any(entry["source_message_id"] == "reply-1" for entry in remembered)
    assert all(step.criterion not in str(models.requests) for step in STEPS)


async def test_failed_step_keeps_prior_state_and_is_not_an_npc_emotion_or_memory():
    models = Models()
    simulation = Trajectory(models, settings())
    await simulation.step(1, STEPS[0])
    before, history = load(simulation.host.state), list(simulation.history)
    models.broken = "proposal"
    failed = await simulation.step(2, STEPS[1])
    assert failed["status"] == "failed" and not failed["response"]
    assert load(simulation.host.state) == before
    assert failed["state_before"] == failed["state_after"]
    assert simulation.history == history and "player-2" not in simulation.sources
    models.broken = None
    resumed = await simulation.step(3, STEPS[2])
    assert resumed["status"] == "ok"
    assert load(simulation.host.state).revision == before.revision + 1


async def test_tampered_source_is_not_reused_in_a_following_decision():
    models = Models()
    simulation = Trajectory(models, settings())
    await simulation.step(1, STEPS[0])
    simulation.sources["reply-1"].content = "Edited narration"
    await simulation.step(2, STEPS[1])
    proposal = [payload for phase, _, payload in models.requests if phase == "proposal"][-1]
    assert not any(
        entry["source_message_id"] == "reply-1"
        for entry in proposal["witnessed_utterances_not_world_facts"]
    )
