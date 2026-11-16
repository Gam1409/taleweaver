"""Gate distribution uploads and optional promotion against the exact release commit."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED = ("ci.yml", "security.yml", "docker.yml", "desktop.yml")
ARCHIVES = (
    "TaleWeaver-windows-X64.zip",
    "TaleWeaver-linux-X64.tar.gz",
    "TaleWeaver-macos-ARM64.tar.gz",
)
ASSETS = {*ARCHIVES, "SHA256SUMS"}
START = "<!-- taleweaver-verified-assets:start -->"
END = "<!-- taleweaver-verified-assets:end -->"


class NotReadyError(RuntimeError):
    """Required evidence is missing or still running; retain the current release status."""


@dataclass(frozen=True)
class Target:
    repo: str
    tag: str
    build_run_id: str = ""
    promote: bool = False

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repo):
            raise ValueError("Invalid repository.")
        if not re.fullmatch(r"v[0-9][A-Za-z0-9._-]{0,99}", self.tag):
            raise ValueError("Invalid release tag.")
        if self.build_run_id and not re.fullmatch(r"[0-9]{1,20}", self.build_run_id):
            raise ValueError("Invalid desktop build run ID.")


@dataclass(frozen=True)
class Plan:
    target: Target
    commit: str
    release: dict[str, Any]
    runs: dict[str, dict[str, Any]]

    @property
    def build(self) -> dict[str, Any]:
        return self.runs["desktop.yml"]

    @property
    def stamp(self) -> str:
        return (
            f"<!-- taleweaver-release-assets:{self.commit}:"
            f"{self.build['id']}:{self.build.get('run_attempt', 1)} -->"
        )

    @property
    def promotion_stamp(self) -> str:
        return f"<!-- taleweaver-release-promoted:{self.target.tag}:{self.commit} -->"


def api(repo: str, path: str, payload: dict | None = None) -> Any:
    args = ["gh", "api", f"repos/{repo}/{path}"]
    body = None
    if payload is not None:
        args.extend(["--method", "PATCH", "--input", "-"])
        body = json.dumps(payload)
    result = subprocess.run(args, input=body, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "GitHub API request failed.")
    return json.loads(result.stdout)


def _runs(target: Target, commit: str) -> list[dict]:
    rows = []
    for page in range(1, 11):
        batch = api(target.repo, f"actions/runs?head_sha={commit}&per_page=100&page={page}")[
            "workflow_runs"
        ]
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise RuntimeError("Too many workflow runs to establish the latest release checks.")


def _trusted(run: dict, target: Target, commit: str) -> bool:
    return bool(
        run.get("head_sha") == commit
        and (run.get("head_repository") or {}).get("full_name") == target.repo
        and (run.get("repository") or {}).get("full_name") == target.repo
        and run.get("event") in {"push", "workflow_dispatch", "schedule"}
    )


def prepare(target: Target) -> Plan:
    commit = api(target.repo, f"commits/{target.tag}")["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid release commit.")
    rows = [run for run in _runs(target, commit) if _trusted(run, target, commit)]
    checks = {}
    for name in REQUIRED:
        latest = max(
            (run for run in rows if run.get("path") == f".github/workflows/{name}"),
            key=lambda run: (run.get("run_number", 0), run.get("run_attempt", 0), run["id"]),
            default=None,
        )
        if latest is None or (latest.get("status"), latest.get("conclusion")) != (
            "completed",
            "success",
        ):
            raise NotReadyError(f"Waiting for the latest successful {name} at {commit}.")
        checks[name] = latest
    if target.build_run_id and str(checks["desktop.yml"]["id"]) != target.build_run_id:
        raise NotReadyError("The requested desktop run is not the latest verified release build.")
    release = api(target.repo, f"releases/tags/{target.tag}")
    if release.get("tag_name") != target.tag or not isinstance(release.get("id"), int):
        raise ValueError("Release identity changed.")
    return Plan(target, commit, release, checks)


def _attached(release: dict) -> bool:
    uploaded = {
        asset["name"]
        for asset in release.get("assets", [])
        if asset.get("state") == "uploaded" and asset.get("size", 0) > 0
    }
    return uploaded >= ASSETS


def complete(plan: Plan) -> bool:
    if not _attached(plan.release):
        return False
    body = plan.release.get("body") or ""
    if plan.target.promote:
        # This is one requested promotion, not a permanent claim on Latest.
        return plan.promotion_stamp in body
    return plan.stamp in body


def _notes(plan: Plan) -> str:
    body = plan.release.get("body") or ""
    prefix, found, remainder = body.partition(START)
    suffix = ""
    if found:
        _, ended, suffix = remainder.partition(END)
        if not ended:
            raise ValueError("The existing verification section is incomplete; notes were kept.")
    checks = " · ".join(
        f"[{name.removesuffix('.yml')}](https://github.com/{plan.target.repo}/actions/runs/{run['id']})"
        for name, run in plan.runs.items()
    )
    section = (
        f"{START}\n## Verified distribution archives\n\n"
        "Windows x64, Linux x64 and macOS ARM64 archives and SHA256SUMS are attached.\n\n"
        f"Source commit: `{plan.commit}`. Completed checks: {checks}.\n\n"
        f"{plan.stamp}\n"
    )
    if plan.target.promote or plan.promotion_stamp in body:
        section += plan.promotion_stamp + "\n"
    section += END
    return prefix.rstrip() + "\n\n" + section + suffix


def publish(target: Target) -> dict:
    """Recheck after upload; a newer failed/pending check cannot promote the release."""
    plan = prepare(target)
    if not _attached(plan.release):
        raise NotReadyError("All three archives and SHA256SUMS must finish uploading first.")
    payload: dict[str, Any] = {"body": _notes(plan)}
    promoting = target.promote and plan.promotion_stamp not in (plan.release.get("body") or "")
    if promoting:
        payload.update(draft=False, prerelease=False, make_latest="true")
    result = api(target.repo, f"releases/{plan.release['id']}", payload)
    if promoting and (result.get("draft") is not False or result.get("prerelease") is not False):
        raise RuntimeError("GitHub did not confirm release promotion.")
    return dict(result)


def _outputs(**values: str) -> None:
    # GITHUB_OUTPUT is a GitHub-owned runner file, never a release/user supplied path.
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write("".join(f"{key}={value}\n" for key, value in values.items()))


def inspect(target: Target) -> None:
    try:
        plan = prepare(target)
    except NotReadyError as exc:
        _outputs(ready="false")
        print(str(exc))
        return
    if complete(plan):
        _outputs(ready="false")
        print("This release delivery is already recorded; no repeat promotion is needed.")
        return
    _outputs(ready="true", build_run_id=str(plan.build["id"]), commit=plan.commit)
    print(f"Verified {target.tag} at {plan.commit}, desktop run {plan.build['id']}.")


def main() -> None:
    target = Target(
        repo=os.environ["GITHUB_REPOSITORY"],
        tag=os.environ["RELEASE_TAG"],
        build_run_id=os.environ.get("BUILD_RUN_ID", ""),
        promote=os.environ.get("PROMOTE_RELEASE", "false").lower() == "true",
    )
    if len(sys.argv) != 2 or sys.argv[1] not in {"inspect", "publish"}:
        raise ValueError("Choose inspect or publish.")
    if sys.argv[1] == "inspect":
        inspect(target)
        return
    result = publish(target)
    print(f"Verified release archives attached: {result['html_url']}")


if __name__ == "__main__":
    main()
