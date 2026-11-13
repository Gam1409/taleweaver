"""Report detector metrics for fixed fictional examples without calling a model.

This is a reproducible detector check, not a benchmark of generated prose quality.
The report includes editorial review notes and deliberately omits source text.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.engine.narrator.flow import analyze_flow
from backend.engine.narrator.settings import NarrationFlow


def evaluate(profile: NarrationFlow) -> dict[str, Any]:
    fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "narration_flow_samples.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    cases = [
        {
            "id": case["id"],
            "language": case["language"],
            "baseline": asdict(analyze_flow(case["baseline"], profile, case["language"])),
            "candidate": asdict(analyze_flow(case["candidate"], profile, case["language"])),
        }
        for case in fixture["cases"]
    ]
    return {
        "fixture_version": fixture["format_version"],
        "purpose": fixture["purpose"],
        "profile": profile,
        "human_review_required": True,
        "editorial_review_notes": fixture["review_notes"],
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("off", "gentle", "balanced"), default="gentle")
    args = parser.parse_args()
    print(json.dumps(evaluate(args.profile), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
