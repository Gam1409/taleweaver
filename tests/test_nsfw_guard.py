"""Required explicit-atom guard: staging storage, snapshot freezing, render checks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.engine.scene_illustrations import render
from backend.engine.scene_illustrations.nsfw_guard import (
    VERSION,
    category_covered,
    differences,
    explicit_atoms,
    requirements,
    status,
)
from backend.engine.scene_staging.schema import SceneExtraction
from backend.engine.scene_staging.state import reconcile
from backend.engine.visual_novel.config import SETTINGS_KEY, read_settings

CAST = [{"id": "ANNA", "name": "Anna"}, {"id": "BORIS", "name": "Boris"}]
SOLO = [{"id": "ANNA", "name": "Anna"}]


def _atom(category: str, participants: list[str]) -> dict:
    return {"category": category, "participants": participants, "evidence": "quote"}


def test_missing_category_detected():
    missing = differences("Anna rests alone on the bed.", [_atom("masturbation", ["ANNA"])], SOLO)
    assert missing == ["Preserve the explicit masturbation act."]


def test_covered_category_passes():
    body = "Anna is masturbating on the bed."
    assert differences(body, [_atom("masturbation", ["ANNA"])], SOLO) == []


def test_weakened_act_detected():
    """A required explicit act softened into milder contact is a failure."""
    body = "Anna and Boris kiss gently. 2 people."
    missing = differences(body, [_atom("vaginal", ["ANNA", "BORIS"])], CAST)
    assert missing == ["Preserve the explicit vaginal act."]


def test_participant_loss_detected():
    body = "Oral pleasure on the sofa. 2 people."
    missing = differences(body, [_atom("oral", ["ANNA", "BORIS"])], CAST)
    assert missing == [
        "Preserve Anna as an explicit act participant.",
        "Preserve Boris as an explicit act participant.",
    ]


def test_all_participants_present_passes():
    body = "Anna and Boris share oral pleasure. 2 people."
    assert differences(body, [_atom("oral", ["ANNA", "BORIS"])], CAST) == []


def test_non_latin_names_checked_verbatim():
    solo = [{"id": "ANNA", "name": "Анна"}]
    assert differences("Анна is masturbating.", [_atom("masturbation", ["ANNA"])], solo) == []
    missing = differences("Anna is masturbating.", [_atom("masturbation", ["ANNA"])], solo)
    assert missing == ["Preserve Анна as an explicit act participant."]


def test_unknown_category_reports_unresolvable():
    missing = differences("Anything.", [_atom("teleport", ["ANNA"])], SOLO)
    assert missing == ["Unknown explicit act category: teleport."]


def test_no_atoms_no_issues():
    assert differences("Anything.", [], CAST) == []
    assert requirements([], CAST) == ""


def test_exact_words_do_not_match_innocent_extensions():
    assert not category_covered("a broad analysis of art", "anal")
    assert category_covered("an anal close-up", "anal")
    assert category_covered("he stripped her corset", "undressing")
    # Prefix matching trades a rare false pass ("striped") for the false fail
    # ("stripped"); a missed undressing atom is the worse outcome.
    assert category_covered("a striped shirt", "undressing")
    assert not category_covered("peacock feathers", "vaginal")


def test_requirements_names_participants_and_demands_verbatim():
    text = requirements([_atom("oral", ["ANNA", "BORIS"])], CAST)
    assert "oral between Anna, Boris" in text
    assert "verbatim" in text
    assert "never translated" in text


def test_status_reports_not_run_without_atoms():
    assert status("warn", [], [])["status"] == "not_run"
    passed = status("block", [_atom("oral", ["ANNA"])], [])
    assert passed["status"] == "passed" and passed["mode"] == "block"
    failed = status("warn", [_atom("oral", ["ANNA"])], ["x"])
    assert failed["status"] == "failed" and failed["version"] == VERSION


def test_explicit_atoms_ignores_malformed_facts():
    assert explicit_atoms(None) == []
    assert explicit_atoms({"explicit": "junk"}) == []
    assert explicit_atoms({"explicit": ["junk", {"participants": ["A"]}]}) == []
    atoms = explicit_atoms({"explicit": [{"category": "oral", "participants": ["A"]}]})
    assert atoms == [{"category": "oral", "participants": ["A"]}]


def _extraction(payload: dict) -> SceneExtraction:
    return SceneExtraction.model_validate(payload)


def test_reconcile_stores_valid_explicit_atoms_and_counts_rejections():
    state = SimpleNamespace(entity_states={}, current_scene_id="s1")
    narration = "Anna and Boris fall onto the bed."
    extraction = _extraction(
        {
            "explicit": [
                {
                    "category": "vaginal",
                    "participants": ["ANNA", "BORIS"],
                    "evidence": "fall onto the bed",
                },
                {
                    "category": "oral",
                    "participants": ["ANNA", "GHOST"],
                    "evidence": "fall onto the bed",
                },
                {
                    "category": "kissing",
                    "participants": ["ANNA", "BORIS"],
                    "evidence": "not in the narration",
                },
            ]
        }
    )
    result = reconcile(state, CAST, narration, extraction)
    assert result["status"] == "ready"
    assert [atom["category"] for atom in result["explicit"]] == ["vaginal"]
    assert result["explicit"][0]["participants"] == ["ANNA", "BORIS"]
    assert result["explicit"][0]["source_hash"] == result["source_hash"]
    assert result["explicit"][0]["evidence"] == "fall onto the bed"
    assert result["explicit_rejected"] == 2


def test_reconcile_allows_solo_masturbation_only():
    state = SimpleNamespace(entity_states={}, current_scene_id="s1")
    narration = "Anna touches herself."
    extraction = _extraction(
        {
            "explicit": [
                {"category": "masturbation", "participants": ["ANNA"], "evidence": "touches herself"},
                {"category": "oral", "participants": ["ANNA"], "evidence": "touches herself"},
            ]
        }
    )
    result = reconcile(state, SOLO, narration, extraction)
    assert [atom["category"] for atom in result["explicit"]] == ["masturbation"]
    assert result["explicit_rejected"] == 1


def test_reconcile_explicit_defaults_empty_without_extractions():
    state = SimpleNamespace(entity_states={}, current_scene_id="s1")
    result = reconcile(state, SOLO, "Anna stands.", SceneExtraction.model_validate({}))
    assert result["explicit"] == []
    assert result["explicit_rejected"] == 0


def test_reconcile_keeps_postures_when_explicit_atoms_fail():
    state = SimpleNamespace(entity_states={}, current_scene_id="s1")
    narration = "Anna sits down slowly."
    extraction = _extraction(
        {
            "changes": [
                {"entity_id": "ANNA", "evidence": "sits down", "posture": "sitting"}
            ],
            "explicit": [
                {"category": "oral", "participants": ["ANNA"], "evidence": "nowhere"}
            ],
        }
    )
    result = reconcile(state, SOLO, narration, extraction)
    assert result["status"] == "ready"
    assert result["actors"]["ANNA"]["posture"]["value"] == "sitting"
    assert result["explicit"] == []
    assert result["explicit_rejected"] == 1


def test_visible_facts_freezes_bounded_explicit_atoms():
    from backend.engine.scene_illustrations.snapshots import _visible_facts

    facts = {
        "explicit": [
            {"category": "oral", "participants": ["A", "", "B"], "evidence": "цитата"},
            "junk",
            {"category": "", "participants": ["A"], "evidence": "x"},
            {"category": "vaginal", "participants": "solo", "evidence": "x"},
        ]
    }
    out = _visible_facts(facts)
    assert out["explicit"] == [
        {"category": "oral", "participants": ["A", "B"], "evidence": "цитата"}
    ]
    assert _visible_facts({})["explicit"] == []
    assert _visible_facts({"explicit": None})["explicit"] == []


def test_nsfw_guard_setting_defaults_to_shadow_and_validates():
    assert read_settings(SimpleNamespace(entity_states={})).nsfw_guard == "warn"
    stored = SimpleNamespace(entity_states={SETTINGS_KEY: {"nsfw_guard": "block"}})
    assert read_settings(stored).nsfw_guard == "block"
    broken = SimpleNamespace(entity_states={SETTINGS_KEY: {"nsfw_guard": "nuke"}})
    assert read_settings(broken).nsfw_guard == "warn"


def _nsfw_state(mode: str) -> SimpleNamespace:
    return SimpleNamespace(
        session_id="guard-test", entity_states={SETTINGS_KEY: {"nsfw_guard": mode}}
    )


async def _build(
    monkeypatch,
    *,
    mode: str,
    body: str,
    explicit: list | None,
    nsfw=True,
    visual_mature=True,
):
    monkeypatch.setattr(
        render,
        "_settings",
        AsyncMock(
            return_value=(
                {"provider": "stable_diffusion", "_nsfw_enabled": nsfw},
                "watercolor",
                "quiet",
            )
        ),
    )
    monkeypatch.setattr(
        render, "select_profile", lambda _options: SimpleNamespace(mature_themes=visual_mature)
    )
    adapt = AsyncMock(return_value=body)
    monkeypatch.setattr(render, "adapt_body", adapt)
    visible = {"characters": [{"id": "ANNA", "name": "Anna"}]}
    if explicit is not None:
        visible["explicit"] = explicit
    snapshot = {"narration": "Anna is on the bed.", "visible_facts": visible}
    request, _ = await render.image_request(
        None, _nsfw_state(mode), SimpleNamespace(encrypted_api_keys={}), snapshot
    )
    details: dict = {}
    request["provider_options"]["_generation_details"] = details
    return request, adapt, details


ACT = [{"category": "masturbation", "participants": ["ANNA"], "evidence": "quote"}]


@pytest.mark.asyncio
async def test_block_mode_refuses_render_when_atoms_lost(monkeypatch):
    request, adapt, details = await _build(
        monkeypatch, mode="block", body="Anna rests on the bed.", explicit=ACT
    )
    with pytest.raises(ValueError, match="lost required explicit scene facts"):
        await render.prepare_moment_prompt(request)
    assert adapt.await_count == 2
    assert details["nsfw_guard"]["status"] == "failed"
    assert details["nsfw_guard"]["mode"] == "block"


@pytest.mark.asyncio
async def test_shadow_mode_proceeds_and_records_failure(monkeypatch):
    request, adapt, details = await _build(
        monkeypatch, mode="warn", body="Anna rests on the bed.", explicit=ACT
    )
    await render.prepare_moment_prompt(request)
    assert adapt.await_count == 2
    assert request["prompt"] == "Anna rests on the bed."
    assert details["nsfw_guard"]["status"] == "failed"
    assert details["nsfw_guard"]["mode"] == "warn"
    assert request["provider_options"]["_prompt_prepared"] is True


@pytest.mark.asyncio
async def test_covered_body_passes_and_injects_contract(monkeypatch):
    request, adapt, details = await _build(
        monkeypatch, mode="block", body="Anna is masturbating on the bed.", explicit=ACT
    )
    await render.prepare_moment_prompt(request)
    adapt.assert_awaited_once()
    _, policy, _ = adapt.call_args.args
    assert "Explicit content fidelity contract" in policy.instructions
    assert "verbatim" in policy.instructions
    assert details["nsfw_guard"]["status"] == "passed"
    assert request["prompt"] == "Anna is masturbating on the bed."


@pytest.mark.asyncio
async def test_off_mode_skips_injection_and_check(monkeypatch):
    request, adapt, details = await _build(
        monkeypatch, mode="off", body="Anna rests on the bed.", explicit=ACT
    )
    await render.prepare_moment_prompt(request)
    adapt.assert_awaited_once()
    _, policy, _ = adapt.call_args.args
    assert "Explicit content fidelity contract" not in policy.instructions
    assert details["nsfw_guard"]["status"] == "not_run"
    assert request["provider_options"]["_prompt_prepared"] is True


@pytest.mark.asyncio
async def test_no_atoms_reports_not_run(monkeypatch):
    request, adapt, details = await _build(
        monkeypatch, mode="block", body="Anna rests on the bed.", explicit=None
    )
    await render.prepare_moment_prompt(request)
    adapt.assert_awaited_once()
    _, policy, _ = adapt.call_args.args
    assert "Explicit content fidelity contract" not in policy.instructions
    assert details["nsfw_guard"]["status"] == "not_run"


@pytest.mark.asyncio
async def test_neutral_route_ignores_explicit_atoms(monkeypatch):
    request, adapt, details = await _build(
        monkeypatch, mode="block", body="Anna rests on the bed.", explicit=ACT, nsfw=False
    )
    await render.prepare_moment_prompt(request)
    adapt.assert_awaited_once()
    _, policy, _ = adapt.call_args.args
    assert "Explicit content fidelity contract" not in policy.instructions
    assert details["nsfw_guard"]["status"] == "not_run"


@pytest.mark.asyncio
async def test_visual_settings_gate_disables_guard(monkeypatch):
    """No adventure-only activation: Visual settings must enable mature themes too."""
    request, adapt, details = await _build(
        monkeypatch,
        mode="block",
        body="Anna rests on the bed.",
        explicit=ACT,
        nsfw=True,
        visual_mature=False,
    )
    await render.prepare_moment_prompt(request)
    adapt.assert_awaited_once()
    _, policy, _ = adapt.call_args.args
    assert "Explicit content fidelity contract" not in policy.instructions
    assert details["nsfw_guard"]["status"] == "not_run"
    assert details["nsfw_guard"]["mode"] == "block"
    assert request["provider_options"]["_prompt_prepared"] is True
