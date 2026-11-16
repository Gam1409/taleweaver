"""Release completion events must reach a guarded, serialized publishing path."""

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"


def workflow(name):
    data = yaml.safe_load((WORKFLOWS / name).read_text())
    if True in data:
        data["on"] = data.pop(True)
    return data


def test_completion_events_cover_every_release_gate():
    expected = {
        workflow(name)["name"] for name in ("ci.yml", "security.yml", "docker.yml", "desktop.yml")
    }
    config = workflow("release-assets.yml")
    assert set(config["on"]["workflow_run"]["workflows"]) == expected
    assert config["on"]["workflow_run"]["types"] == ["completed"]


def test_automatic_promotion_is_scoped_and_manual_promotion_is_opt_in():
    config = workflow("release-assets.yml")
    inputs = config["on"]["workflow_dispatch"]["inputs"]
    assert inputs["promote"]["default"] is False
    assert inputs["build_run_id"]["required"] is False
    assert config["concurrency"]["cancel-in-progress"] is False
    job = config["jobs"]["attach"]
    assert "head_sha" not in job["if"]
    assert "github.event.workflow_run.conclusion == 'success'" in job["if"]
    assert "head_repository.full_name == github.repository" in job["if"]
    steps = job["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    assert checkout["with"]["persist-credentials"] is False
    scripts = [step.get("run", "") for step in steps]
    inspect = next(i for i, script in enumerate(scripts) if "release_assets.py inspect" in script)
    upload = next(i for i, script in enumerate(scripts) if "gh release upload" in script)
    publish = next(i for i, script in enumerate(scripts) if "release_assets.py publish" in script)
    assert inspect < upload < publish
    assert all(
        step.get("if") == "steps.verify.outputs.ready == 'true'" for step in steps[inspect + 1 :]
    )


def test_archive_names_agree_between_gate_and_upload():
    from scripts.release_assets import ASSETS

    config = workflow("release-assets.yml")
    upload = next(
        step["run"]
        for step in config["jobs"]["attach"]["steps"]
        if "gh release upload" in step.get("run", "")
    )
    assert all(f"release-dist/{name}" in upload for name in ASSETS)
