"""Bounded private evaluation output; never store endpoints or provider credentials."""

import json
from pathlib import Path

from backend.utils.path_security import ensure_within_base_dir, sanitize_path_component

ROOT = Path(__file__).resolve().parents[2] / "log" / "live-contracts"
MAX_BYTES = 32 * 1024 * 1024


def folder(run_id: str) -> Path:
    if not run_id or len(run_id) > 80 or sanitize_path_component(run_id) != run_id:
        raise ValueError("Invalid evaluation run ID.")
    return Path(ensure_within_base_dir(str(ROOT / run_id), str(ROOT)))


def target(directory: Path, name: str) -> Path:
    if name not in {
        "manifest.json",
        "results.jsonl",
        "calls.jsonl",
        "ratings.jsonl",
        "review.md",
        "summary.json",
        "inference-reservations.json",
    }:
        raise ValueError("Unknown evaluation artifact.")
    return Path(ensure_within_base_dir(str(directory / name), str(ROOT)))


def create(run_id: str, plan: dict) -> Path:
    directory = folder(run_id)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    write(directory, "manifest.json", plan)
    return directory


def write(directory: Path, name: str, value: dict) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2)
    if len(content.encode()) > MAX_BYTES:
        raise ValueError("Evaluation artifact exceeds its byte limit.")
    target(directory, name).write_text(content, encoding="utf-8")


def append(directory: Path, name: str, value: dict) -> None:
    content = json.dumps(value, ensure_ascii=False) + "\n"
    path = target(directory, name)
    size = path.stat().st_size if path.exists() else 0
    if size + len(content.encode()) > MAX_BYTES:
        raise ValueError("Evaluation artifact limit reached; earlier records were retained.")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(content)


def read(directory: Path, name: str) -> str:
    path = target(directory, name)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Evaluation artifact exceeds its byte limit.")
    return path.read_text(encoding="utf-8")


def records(directory: Path, name: str) -> list[dict]:
    path = target(directory, name)
    if not path.exists():
        return []
    return [json.loads(line) for line in read(directory, name).splitlines() if line.strip()]


def write_text(directory: Path, name: str, content: str) -> None:
    if len(content.encode()) > MAX_BYTES:
        raise ValueError("Evaluation artifact exceeds its byte limit.")
    target(directory, name).write_text(content, encoding="utf-8")
