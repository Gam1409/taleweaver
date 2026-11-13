"""The offline evaluation needs no configured model and never exports example prose."""

import json
import os
import runpy
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("profile", ["gentle", "balanced", "off"])
def test_offline_evaluation_reports_metrics_and_review_without_model_keys(
    profile, monkeypatch, capsys
):
    for key in tuple(os.environ):
        if key.endswith("API_KEY") or key in {"ENCRYPTION_KEY", "SECRET_KEY"}:
            monkeypatch.delenv(key)
    monkeypatch.setattr(sys, "argv", ["evaluate_narration_flow.py", "--profile", profile])
    runpy.run_path(str(PROJECT_ROOT / "scripts/evaluate_narration_flow.py"), run_name="__main__")
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["profile"] == profile
    assert report["human_review_required"] is True
    assert len(report["editorial_review_notes"]) >= 3
    assert {case["language"] for case in report["cases"]} == {
        "English",
        "Russian",
        "Arabic",
        "Japanese",
        "Chinese",
        "Korean",
    }
    fixture = json.loads(
        (PROJECT_ROOT / "tests/fixtures/narration_flow_samples.json").read_text(encoding="utf-8")
    )
    for case in fixture["cases"]:
        for text in (*case["baseline"], *case["candidate"]):
            assert text not in output
    assert "[curious]" not in output
    assert all(case["baseline"]["signals"] == [] for case in report["cases"]) is (profile == "off")
