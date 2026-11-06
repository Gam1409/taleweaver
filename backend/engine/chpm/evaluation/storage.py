"""Private, bounded artifacts below log/, never served as game assets."""

import json
from pathlib import Path
from typing import Any

from backend.engine.chpm.evaluation.contracts import Case, Rating, Result
from backend.engine.chpm.evaluation.report import blind_document, pairs, summarize, template
from backend.engine.chpm.kernel import fingerprint
from backend.utils.path_security import ensure_within_base_dir, sanitize_path_component

ROOT = Path(__file__).resolve().parents[4] / "log" / "chpm-evaluations"
MAX_BYTES = 32 * 1024 * 1024


def directory(run_id: str) -> Path:
    if sanitize_path_component(run_id) != run_id:
        raise ValueError("Use a run ID containing only letters, digits, underscores or hyphens.")
    return Path(ensure_within_base_dir(str(ROOT / run_id), str(ROOT)))


def path(folder: Path, name: str) -> Path:
    return Path(ensure_within_base_dir(str(folder / name), str(ROOT)))


def create(run_id: str, manifest: dict[str, Any]) -> Path:
    folder = directory(run_id)
    folder.mkdir(parents=True, exist_ok=False)
    path(folder, "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    path(folder, "results.jsonl").touch(exist_ok=False)
    return folder


def append(folder: Path, result: Result) -> None:
    target = path(folder, "results.jsonl")
    line = result.model_dump_json() + "\n"
    if target.stat().st_size + len(line.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Evaluation file limit exceeded; earlier results remain available.")
    with target.open("a", encoding="utf-8") as handle:
        handle.write(line)


def read(folder: Path, name: str) -> str:
    target = path(folder, name)
    if target.stat().st_size > MAX_BYTES:
        raise ValueError("Evaluation artifact exceeds its size limit.")
    return target.read_text(encoding="utf-8")


def load(folder: Path) -> tuple[dict, list[Case], list[Result]]:
    manifest = json.loads(read(folder, "manifest.json"))
    cases = [Case.model_validate(value) for value in manifest["cases"]]
    results = [
        Result.model_validate_json(line)
        for line in read(folder, "results.jsonl").splitlines()
        if line.strip()
    ]
    allowed = {raw["id"]: fingerprint(raw) for raw in manifest["cases"]}
    for result in results:
        if (
            result.case_hash != allowed.get(result.case_id)
            or not 1 <= result.repetition <= manifest["repeats"]
        ):
            raise ValueError("Result does not match the saved evaluation cases.")
        if result.pair_id != f"{result.case_id}-{result.repetition}":
            raise ValueError("Result pair ID does not match its case and repetition.")
    return manifest, cases, results


def finish(folder: Path) -> None:
    manifest, cases, results = load(folder)
    seed = manifest["blind_seed"]
    path(folder, "review.md").write_text(blind_document(results, cases, seed), encoding="utf-8")
    with path(folder, "ratings.jsonl").open("x", encoding="utf-8") as handle:
        for identifier, group in pairs(results, seed).items():
            handle.write(template(identifier, group).model_dump_json() + "\n")
    report(folder)


def report(folder: Path) -> str:
    manifest, cases, results = load(folder)
    ratings = [
        Rating.model_validate_json(line)
        for line in read(folder, "ratings.jsonl").splitlines()
        if line.strip()
    ]
    text = summarize(results, ratings, manifest["blind_seed"], len(cases) * manifest["repeats"] * 2)
    path(folder, "summary.md").write_text(text, encoding="utf-8")
    return text
