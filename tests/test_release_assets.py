"""Release promotion needs trusted checks, complete uploads and the latest build attempt."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts import release_assets as release

SHA = "5c291c971ddac8fbda26ed8060b57fc2fad4a7d3"
REPO = "Gam1409/taleweaver"
TAG = "v0.7.1-beta"


@pytest.fixture
def world(monkeypatch):
    runs = [
        {
            "id": 100 + index,
            "run_number": 10,
            "run_attempt": 1,
            "head_sha": SHA,
            "path": f".github/workflows/{name}",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "head_repository": {"full_name": REPO},
            "repository": {"full_name": REPO},
        }
        for index, name in enumerate(release.REQUIRED)
    ]
    state = SimpleNamespace(
        runs=runs,
        patches=[],
        latest="v0.7.0-beta",
        release={
            "id": 55,
            "tag_name": TAG,
            "draft": False,
            "prerelease": True,
            "body": "Author release notes.\n",
            "html_url": f"https://github.com/{REPO}/releases/tag/{TAG}",
            "assets": [],
        },
    )

    def api(repo, path, payload=None):
        assert repo == REPO
        if path == f"commits/{TAG}":
            return {"sha": SHA}
        if path.startswith("actions/runs?"):
            return {"workflow_runs": deepcopy(state.runs)}
        if path == f"releases/tags/{TAG}":
            return deepcopy(state.release)
        if path == "releases/latest":
            return {"tag_name": state.latest}
        assert path == "releases/55" and payload is not None
        state.patches.append(deepcopy(payload))
        state.release.update(payload)
        if payload.get("make_latest") == "true":
            state.latest = TAG
        return deepcopy(state.release)

    monkeypatch.setattr(release, "api", api)
    return state


def uploaded(world):
    world.release["assets"] = [
        {"name": name, "state": "uploaded", "size": 42} for name in release.ASSETS
    ]


def test_published_beta_is_eligible_without_recreating_or_hiding_it(world):
    plan = release.prepare(release.Target(REPO, TAG, promote=True))
    assert plan.commit == SHA and plan.build["id"] == 103
    assert not plan.release["draft"] and plan.release["prerelease"]
    assert not release.complete(plan)
    assert not world.patches


@pytest.mark.parametrize("name", release.REQUIRED)
@pytest.mark.parametrize("status", ["queued", "in_progress", "failure", "cancelled", "missing"])
def test_every_gate_must_have_a_successful_latest_trusted_run(world, name, status):
    old = next(row for row in world.runs if row["path"].endswith(name))
    if status == "missing":
        world.runs.remove(old)
    else:
        latest = deepcopy(old)
        latest.update(id=old["id"] + 1000, run_number=11)
        latest.update(
            status=status if status in {"queued", "in_progress"} else "completed",
            conclusion=None if status in {"queued", "in_progress"} else status,
        )
        world.runs.append(latest)
    with pytest.raises(release.NotReadyError, match=name):
        release.publish(release.Target(REPO, TAG, promote=True))
    assert not world.patches


@pytest.mark.parametrize("change", ["commit", "fork", "pull_request", "repository"])
def test_foreign_or_pull_request_build_cannot_supply_release_archives(world, change):
    desktop = world.runs[-1]
    if change == "commit":
        desktop["head_sha"] = "a" * 40
    elif change == "fork":
        desktop["head_repository"] = {"full_name": "someone/fork"}
    elif change == "repository":
        desktop["repository"] = {"full_name": "someone/fork"}
    else:
        desktop["event"] = "pull_request"
    with pytest.raises(release.NotReadyError, match="desktop.yml"):
        release.prepare(release.Target(REPO, TAG))


def test_untrusted_newer_success_cannot_override_a_failed_trusted_build(world):
    trusted = world.runs[-1]
    trusted["conclusion"] = "failure"
    forged = deepcopy(trusted)
    forged.update(run_number=999, conclusion="success", event="pull_request")
    world.runs.append(forged)
    with pytest.raises(release.NotReadyError, match="desktop.yml"):
        release.prepare(release.Target(REPO, TAG))


def test_explicit_build_id_cannot_select_an_old_success(world):
    with pytest.raises(release.NotReadyError, match="latest verified"):
        release.prepare(release.Target(REPO, TAG, build_run_id="99"))
    assert release.prepare(release.Target(REPO, TAG, build_run_id="103")).build["id"] == 103


@pytest.mark.parametrize("missing", sorted(release.ASSETS))
def test_missing_upload_keeps_prerelease_status(world, missing):
    uploaded(world)
    world.release["assets"] = [a for a in world.release["assets"] if a["name"] != missing]
    with pytest.raises(release.NotReadyError, match="finish uploading"):
        release.publish(release.Target(REPO, TAG, promote=True))
    assert world.release["prerelease"] and not world.patches


@pytest.mark.parametrize("change", [{"state": "new"}, {"size": 0}])
def test_incomplete_asset_is_not_a_finished_upload(world, change):
    uploaded(world)
    world.release["assets"][0].update(change)
    with pytest.raises(release.NotReadyError):
        release.publish(release.Target(REPO, TAG, promote=True))
    assert not world.patches


def test_latest_promotion_follows_uploads_and_preserves_author_notes(world):
    uploaded(world)
    result = release.publish(release.Target(REPO, TAG, promote=True))
    assert result["draft"] is False and result["prerelease"] is False
    assert world.latest == TAG
    assert world.patches[0]["make_latest"] == "true"
    assert result["body"].startswith("Author release notes.\n")
    assert all(f"/actions/runs/{run['id']}" in result["body"] for run in world.runs)
    assert release.complete(release.prepare(release.Target(REPO, TAG, promote=True)))


def test_manual_attachment_does_not_implicitly_publish_a_draft(world):
    uploaded(world)
    world.release["draft"] = True
    result = release.publish(release.Target(REPO, TAG))
    assert result["draft"] and result["prerelease"]
    assert world.latest == "v0.7.0-beta"
    assert set(world.patches[0]) == {"body"}


def test_newer_failed_attempt_after_inspection_prevents_promotion(world):
    release.prepare(release.Target(REPO, TAG))
    uploaded(world)
    newer = deepcopy(world.runs[0])
    newer.update(run_attempt=2, conclusion="failure")
    world.runs.append(newer)
    with pytest.raises(release.NotReadyError, match="ci.yml"):
        release.publish(release.Target(REPO, TAG, promote=True))
    assert not world.patches


def test_pending_inspection_is_retryable_and_does_not_write_release_metadata(
    world, monkeypatch, tmp_path
):
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    world.runs[0]["status"] = "queued"
    release.inspect(release.Target(REPO, TAG, promote=True))
    assert output.read_text() == "ready=false\n"
    assert not world.patches


def test_ready_inspection_selects_source_run_and_complete_release_skips_repeat_work(
    world, monkeypatch, tmp_path
):
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    target = release.Target(REPO, TAG, promote=True)
    release.inspect(target)
    assert output.read_text() == f"ready=true\nbuild_run_id=103\ncommit={SHA}\n"
    uploaded(world)
    release.publish(target)
    output.write_text("")
    release.inspect(target)
    assert output.read_text() == "ready=false\n"
    assert len(world.patches) == 1


def test_later_desktop_attempt_requires_fresh_archive_verification(world):
    uploaded(world)
    target = release.Target(REPO, TAG)
    release.publish(target)
    newer = deepcopy(world.runs[-1])
    newer["run_attempt"] = 2
    world.runs.append(newer)
    assert not release.complete(release.prepare(target))
    result = release.publish(target)
    assert result["body"].count(release.START) == 1
    assert f"{SHA}:103:2" in result["body"]
    assert f"{SHA}:103:1" not in result["body"]


def test_completed_promotion_does_not_reclaim_latest_from_a_future_release(
    world, monkeypatch, tmp_path
):
    uploaded(world)
    target = release.Target(REPO, TAG, promote=True)
    release.publish(target)
    world.latest = "v0.8.0"
    world.runs[-1]["run_attempt"] = 2
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    release.inspect(target)
    assert output.read_text() == "ready=false\n"
    assert world.latest == "v0.8.0" and len(world.patches) == 1


def test_repairing_a_missing_asset_after_promotion_preserves_later_owner_status(world):
    uploaded(world)
    target = release.Target(REPO, TAG, promote=True)
    release.publish(target)
    world.latest = "v0.8.0"
    world.release["prerelease"] = True
    world.release["assets"].pop()
    assert not release.complete(release.prepare(target))
    uploaded(world)
    result = release.publish(target)
    assert result["prerelease"] is True
    assert world.latest == "v0.8.0" and set(world.patches[-1]) == {"body"}


def test_existing_verification_section_preserves_following_author_text(world):
    uploaded(world)
    world.release["body"] += release.START + "\nOld verification\n" + release.END + "\nMore notes."
    result = release.publish(release.Target(REPO, TAG, promote=True))
    assert result["body"].endswith("\nMore notes.")
    assert "Old verification" not in result["body"]


@pytest.mark.parametrize(
    "repo,tag,run",
    [
        ("bad/repo/path", TAG, ""),
        (REPO, "v1\nready=true", ""),
        (REPO, "../main", ""),
        (REPO, TAG, "1; echo ignored"),
        (REPO, TAG, "1" * 21),
    ],
)
def test_invalid_release_coordinates_are_rejected_before_api(repo, tag, run):
    with pytest.raises(ValueError):
        release.Target(repo, tag, run)


def test_api_patches_use_json_stdin_and_never_interpolate_release_notes_in_shell(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"draft":false}', stderr="")

    monkeypatch.setattr(release.subprocess, "run", run)
    payload = {"body": "First line.\nLiteral `ticks` and $(placeholder)."}
    assert release.api(REPO, "releases/55", payload) == {"draft": False}
    assert calls[0][0][-4:] == ["--method", "PATCH", "--input", "-"]
    assert json.loads(calls[0][1]["input"]) == payload
    assert "shell" not in calls[0][1]
