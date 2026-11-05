"""Personality comparisons keep circumstances matched and never rewrite traits."""

from backend.engine.chpm.evaluation import character_stress, personas
from backend.engine.chpm.evaluation.cases import cases, choose
from backend.engine.chpm.evaluation.runner import run_arm
from backend.engine.personality.profile import CATALOG
from tests.test_chpm_evaluation import Models, settings


def test_all_dina_states_share_every_canonical_trait_and_authored_identity():
    variants = character_stress.cases()
    assert len(variants) == 7
    assert {case.character for case in variants} == {character_stress.CARD.strip()}
    assert {case.goal for case in variants} == {character_stress.GOAL}
    for case in variants:
        profile = case.personality.model_dump()
        assert set(profile) == set(CATALOG)
        assert all(value in CATALOG[key][1] for key, value in profile.items())
        assert profile == character_stress.PROFILE.model_dump()


def test_persona_cases_vary_character_but_match_each_situation():
    variants = [case for case in cases() if case.id.startswith("persona_")]
    assert len(variants) == 2 * len(personas.PROFILES)
    for suffix in ("short-ru", "long40-ru"):
        condition = [case for case in variants if case.id.endswith(suffix)]
        assert len({case.character for case in condition}) == len(personas.PROFILES)
        assert len({case.message for case in condition}) == 1
        assert len({case.goal for case in condition}) == 1
        assert len({case.scene for case in condition}) == 1
        assert all(case.history == condition[0].history for case in condition)


async def test_full_profile_reaches_both_roles_without_test_rubric():
    case = choose(["dina_fear-ru"])[0]
    before = case.model_dump()
    models = Models()
    result = await run_arm(case, 1, "chpm", models, settings())
    assert result.status == "ok", result.error_detail
    proposal = next(payload for phase, _, payload in models.requests if phase == "proposal")
    narrator = next(payload for phase, _, payload in models.requests if phase == "narration")
    assert proposal["authored_character"] == case.character == narrator["character"]
    assert "Usually composed" in str(proposal) and "Usually composed" in narrator["personality"]
    assert case.rubric not in str(models.requests)
    assert case.model_dump() == before
