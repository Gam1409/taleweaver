"""Independent annotation first; compare model signals only after a blind reading."""

import hashlib
import json
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import artifacts
from .scenarios import CONTEXT, goal


class Rating(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_id: str
    result_hash: str
    status: Literal["pending", "reviewed"] = "pending"
    inferred_internal: list[str] | None = None
    narrated: list[str] | None = None
    dialogue: list[str] | None = None
    evidence_quotes: list[str] = Field(default_factory=list)
    contextually_grounded: bool | None = None
    initiative: bool | None = None
    unnecessary_permission: bool | None = None
    preserves_player_agency: bool | None = None
    action_matches_state: bool | None = None
    notes: str = ""

    @model_validator(mode="after")
    def complete(self):
        required = (
            self.inferred_internal,
            self.narrated,
            self.dialogue,
            self.contextually_grounded,
            self.initiative,
            self.unnecessary_permission,
            self.preserves_player_agency,
            self.action_matches_state,
        )
        if self.status == "reviewed" and (
            any(value is None for value in required) or not self.evidence_quotes
        ):
            raise ValueError(
                "Reviewed samples need independent labels, evidence and all behavioral judgments."
            )
        return self


def identifier(row: dict) -> str:
    return hashlib.sha256(
        f"{row['case_id']}:{row['repetition']}:{row['turn']}".encode()
    ).hexdigest()[:16]


def fingerprint(row: dict) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def prose(row: dict) -> str:
    return "\n".join(message.get("content", "") for message in row["messages"])


def new_internal(row: dict) -> list[str] | None:
    def experiences(snapshot):
        kernel = (snapshot["state"].get("entity_states") or {}).get("__chpm__", {})
        mind = kernel.get("minds", {}).get("LINA", {})
        snapshot = mind.get("snapshot", {})
        events = snapshot.get("journal", []) + [
            event for block in snapshot.get("archive", []) for event in block["events"]
        ]
        return {
            event["event_id"]: event["payload"]
            for event in events
            if event["payload"]["kind"] == "experience"
        }

    previous, current = experiences(row["before"]), experiences(row["after"])
    added = [
        value
        for key, value in current.items()
        if key not in previous and value["channel"] == "affect"
    ]
    if not added:
        return None
    return sorted({value["dimension"] for value in added if value["level"] != "absent"})


def checked_ratings(rows: list[dict], ratings: list[Rating]) -> dict[str, Rating]:
    samples = {identifier(row): row for row in rows}
    result = {}
    for rating in ratings:
        row = samples.get(rating.sample_id)
        if row is None or rating.result_hash != fingerprint(row) or rating.sample_id in result:
            raise ValueError("Ratings have a duplicate, unknown or modified sample.")
        if any(not quote or quote not in prose(row) for quote in rating.evidence_quotes):
            raise ValueError(
                "Annotation evidence must quote the current generated response exactly."
            )
        result[rating.sample_id] = rating
    return result


def statistics(rows: list[dict], ratings: list[Rating]) -> dict:
    checked = checked_ratings(rows, ratings)
    reviewed = [
        (row, checked[identifier(row)])
        for row in rows
        if identifier(row) in checked and checked[identifier(row)].status == "reviewed"
    ]
    dimensions = Counter(label for row in rows for label in new_internal(row) or [])
    independent = {
        channel: dict(
            Counter(label for _, rating in reviewed for label in getattr(rating, channel) or [])
        )
        for channel in ("inferred_internal", "narrated", "dialogue")
    }
    comparable = [
        (row.get("model_reported_affect"), rating.inferred_internal)
        for row, rating in reviewed
        if row.get("model_reported_affect") is not None
    ]
    return {
        "completed_turns": sum(row["completed"] for row in rows),
        "technical_failures": sum(bool(row["errors"]) or not row["completed"] for row in rows),
        "reviewed_samples": len(reviewed),
        "pending_samples": len(rows) - len(reviewed),
        "conditions": {
            mode: {
                "turns": sum(row.get("mode") == mode for row in rows),
                "reviewed": sum(row.get("mode") == mode for row, _ in reviewed),
                "narrated_label_counts": dict(
                    Counter(
                        label
                        for row, rating in reviewed
                        if row.get("mode") == mode
                        for label in rating.narrated or []
                    )
                ),
                "dialogue_label_counts": dict(
                    Counter(
                        label
                        for row, rating in reviewed
                        if row.get("mode") == mode
                        for label in rating.dialogue or []
                    )
                ),
            }
            for mode in ("off", "live")
        },
        "new_accepted_model_affect_counts": dict(dimensions),
        "model_reported_affect_counts": dict(
            Counter(label for row in rows for label in row.get("model_reported_affect") or [])
        ),
        "independent_label_counts": independent if reviewed else None,
        "internal_comparison_samples": len(comparable),
        "internal_exact_set_agreement": sum(
            set(left) == set(right or []) for left, right in comparable
        )
        / len(comparable)
        if comparable
        else None,
        "behavior_counts": {
            field: sum(getattr(rating, field) is True for _, rating in reviewed)
            for field in (
                "contextually_grounded",
                "initiative",
                "unnecessary_permission",
                "preserves_player_agency",
                "action_matches_state",
            )
        }
        if reviewed
        else None,
        "scope": "Descriptive counts for this authored sample, not population prevalence, calibrated psychology or proof of consciousness. Hidden experience may legitimately differ from speech/display. No unreviewed sample is scored as correct.",
    }


def blind_document(rows: list[dict]) -> str:
    lines = [
        "# Independent scene review",
        "",
        "Read context and generated prose before inspecting calls/state/portrait labels. Annotate inferred internal, narrated and spoken affect separately. Use multiple labels or [] for none; null means unreviewed. Check exact evidence quotes. Agreement, refusal, waiting and fictional mistakes can all be grounded. A question is a defect only when unnecessary; do not reward constant action.",
        "",
    ]
    for row in sorted(rows, key=identifier):
        lines.extend(
            [
                f"## Sample {identifier(row)}",
                "",
                CONTEXT,
                "",
                f"Character motive: {goal(row['scenario'])}",
                "",
                "Prior narrated context:\n" + "\n".join(row.get("prior_prose", [])),
                "",
                f"Player input: {row['input']}",
                "",
                prose(row),
                "",
            ]
        )
    return "\n".join(lines)


def review_run(run_id: str) -> int:
    directory = artifacts.folder(run_id)
    rows = artifacts.records(directory, "results.jsonl")
    if not rows:
        raise ValueError("This run has no saved results to review.")
    review = artifacts.target(directory, "review.md")
    if not review.exists():
        artifacts.write_text(directory, "review.md", blind_document(rows))
    ratings_path = artifacts.target(directory, "ratings.jsonl")
    if not ratings_path.exists():
        for row in rows:
            artifacts.append(
                directory,
                "ratings.jsonl",
                Rating(sample_id=identifier(row), result_hash=fingerprint(row)).model_dump(),
            )
    ratings = [Rating.model_validate(row) for row in artifacts.records(directory, "ratings.jsonl")]
    summary = statistics(rows, ratings)
    artifacts.write(directory, "summary.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0
