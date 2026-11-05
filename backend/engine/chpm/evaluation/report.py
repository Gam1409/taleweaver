"""Blind pairing and descriptive statistics, never automatic literary scores."""

import math
from collections import Counter
from statistics import mean

from backend.engine.chpm.evaluation.contracts import Case, Rating, Result
from backend.engine.chpm.kernel import digest

DIMENSIONS = ("voice", "initiative", "relevant_questions", "continuity")


def pairs(results: list[Result], seed: str) -> dict[str, dict[str, Result]]:
    grouped: dict[str, dict[str, Result]] = {}
    for result in results:
        group = grouped.setdefault(result.pair_id, {})
        if result.arm in group:
            raise ValueError("Duplicate result for an evaluation arm.")
        if group and any(other.case_hash != result.case_hash for other in group.values()):
            raise ValueError("Evaluation pair has different case inputs.")
        group[result.arm] = result
    return {
        key: _blind(group, digest(seed + key)[0] in "01234567")
        for key, group in grouped.items()
        if len(group) == 2
    }


def _blind(group: dict[str, Result], reverse: bool) -> dict[str, Result]:
    arms = ("chpm", "baseline") if reverse else ("baseline", "chpm")
    return dict(zip(("A", "B"), (group[arm] for arm in arms), strict=True))


def template(pair_id: str, group: dict[str, Result]) -> Rating:
    return Rating.model_validate(
        {
            "pair_id": pair_id,
            "response_hashes": {label: digest(result.response) for label, result in group.items()},
            **{dimension: {"A": None, "B": None} for dimension in DIMENSIONS},
        }
    )


def blind_document(results: list[Result], cases: list[Case], seed: str) -> str:
    by_id = {case.id: case for case in cases}
    sections = [
        "# Blind dialogue comparison",
        "Compare A and B without opening raw results or the run manifest. Higher scores (0–4) are better. "
        "A necessary question is good; do not count every question or refusal as a defect. "
        "Score voice, grounded initiative, question relevance, and continuity. "
        "Leave unknown values null. Mark unavailable pairs unrateable. "
        "Fill ratings.jsonl; use reason to explain preferences. No automatic judge is used.",
    ]
    for identifier, group in pairs(results, seed).items():
        case = by_id[group["A"].case_id]
        sections.extend(
            [
                f"## {identifier}",
                "Character and goal:",
                _quoted(case.name + "\n" + case.character + "\n" + case.goal),
                "Authored personality fields:",
                _quoted(case.personality.model_dump_json()),
                "Scene and history:",
                _quoted(
                    case.scene
                    + "\n"
                    + "\n".join(f"{line.speaker}: {line.text}" for line in case.history)
                ),
                "Player input:",
                _quoted(case.message),
                "Review criterion: " + case.rubric,
            ]
        )
        for label, result in group.items():
            sections.extend(
                [
                    f"### {label}",
                    _quoted(
                        result.response
                        if result.status == "ok"
                        else "[Response unavailable; pair is not rateable.]"
                    ),
                ]
            )
    return "\n\n".join(sections) + "\n"


def _quoted(text: str) -> str:
    return "\n".join("    " + line for line in text.splitlines())


def _percentile(values: list[float], fraction: float) -> str:
    if not values:
        return "unknown"
    return f"{sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]:.0f}"


def _cost_row(arm: str, results: list[Result]) -> str:
    attempted = [result for result in results if result.arm == arm]
    successful = [result for result in attempted if result.status == "ok"]
    calls = [call for result in attempted for call in result.calls]
    known = [
        call
        for call in calls
        if call.prompt_tokens is not None and call.completion_tokens is not None
    ]
    tokens = (
        str(sum((call.prompt_tokens or 0) + (call.completion_tokens or 0) for call in known))
        if known
        else "unknown"
    )
    if known and len(known) != len(calls):
        tokens += " (partial; total unknown)"
    duration = [result.elapsed_ms for result in successful]
    repairs = sum(call.phase == "repair" for call in calls)
    return f"| {arm} | {len(attempted)} | {len(attempted) - len(successful)} | {len(calls)} | {repairs} | {_percentile(duration, 0.5)} / {_percentile(duration, 0.95)} | {len(known)}/{len(calls)} | {tokens} |"


def summarize(results: list[Result], ratings: list[Rating], seed: str, planned: int) -> str:
    groups = pairs(results, seed)
    valid = _ratings(groups, ratings)
    lines = [
        "# CHPM isolated dialogue evaluation",
        "This compares an authored strong baseline with the CHPM dialogue pipeline; it is not a full TaleWeaver game-session benchmark.",
        f"Recorded arms: {len(results)}/{planned}. Complete pairs: {len(groups)}. Fully human-rated successful pairs: {len(valid)}.",
        "| Arm | Attempts | Failures | Logical calls | Repairs | Final-text latency p50 / p95 ms | Usage coverage | Reported input + output tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
        _cost_row("baseline", results),
        _cost_row("chpm", results),
        "Latency percentiles use successful arms only (nearest rank); failed attempts and their logical calls remain counted. No streaming first-token latency is measured. "
        "Usage is provider-reported, never estimated from characters. Transport retries and unreported failed requests may add cost; these are not billing totals.",
    ]
    failures = Counter(
        (result.arm, result.error_type) for result in results if result.status == "failed"
    )
    lines.extend(
        f"Failure {arm}: {error} × {count}" for (arm, error), count in sorted(failures.items())
    )
    if not valid:
        lines.append(
            "Quality verdict: pending human review. Passing schemas or mock tests is not evidence of better dialogue."
        )
        return _document(lines)
    wins: Counter[str] = Counter()
    lines.extend(
        [
            "Human scores (higher is better; paired descriptive differences, not statistical significance):",
            "| Dimension | Baseline mean | CHPM mean | Mean paired difference |",
            "|---|---:|---:|---:|",
        ]
    )
    for dimension in DIMENSIONS:
        baseline, chpm = _scores(valid, groups, dimension)
        lines.append(
            f"| {dimension} | {mean(baseline):.2f} | {mean(chpm):.2f} | {mean(b - a for a, b in zip(baseline, chpm, strict=True)):+.2f} |"
        )
    for rating in valid:
        winner = (
            groups[rating.pair_id][rating.preferred].arm
            if rating.preferred in {"A", "B"}
            else "tie"
        )
        wins[winner] += 1
    lines.append(
        f"Preferences: baseline {wins['baseline']}, CHPM {wins['chpm']}, ties {wins['tie']}. Small or selectively rated samples do not establish general improvement."
    )
    return _document(lines)


def _document(lines: list[str]) -> str:
    blocks: list[str] = []
    for line in lines:
        if line.startswith("|") and blocks and blocks[-1].startswith("|"):
            blocks[-1] += "\n" + line
        else:
            blocks.append(line)
    return "\n\n".join(blocks) + "\n"


def _ratings(groups: dict[str, dict[str, Result]], ratings: list[Rating]) -> list[Rating]:
    seen = set()
    valid = []
    for rating in ratings:
        if rating.pair_id in seen or rating.pair_id not in groups:
            raise ValueError("Duplicate or unknown rating pair.")
        seen.add(rating.pair_id)
        group = groups[rating.pair_id]
        if rating.response_hashes != template(rating.pair_id, group).response_hashes:
            raise ValueError("Rating refers to changed responses or a different blind assignment.")
        complete = all(
            value is not None
            for dimension in DIMENSIONS
            for value in getattr(rating, dimension).values()
        )
        if rating.preferred in {None, "unrateable"} or not complete:
            continue
        if any(result.status != "ok" for result in group.values()):
            raise ValueError("Failed arms cannot receive quality scores.")
        valid.append(rating)
    return valid


def _scores(
    ratings: list[Rating], groups: dict[str, dict[str, Result]], dimension: str
) -> tuple[list[int], list[int]]:
    scores: dict[str, list[int]] = {"baseline": [], "chpm": []}
    for rating in ratings:
        for label, result in groups[rating.pair_id].items():
            scores[result.arm].append(getattr(rating, dimension)[label])
    return scores["baseline"], scores["chpm"]
