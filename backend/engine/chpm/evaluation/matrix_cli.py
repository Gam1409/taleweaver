"""Plan freely; live matrix execution requires explicit cases, endpoint and total call quota."""

import argparse
import asyncio
import json
from dataclasses import asdict

from backend.engine.chpm.evaluation import matrix_cases


def manifest(
    cases: list[matrix_cases.MatrixCase],
    *,
    all_present: bool = False,
    max_output_tokens: int | None = None,
) -> dict:
    return {
        "suite": "chpm-cast-matrix-v4",
        "scope": "Synthetic source histories; production perception, cognition, scheduling, narration, review and commit. No game DB or image generation.",
        "cases": [asdict(case) for case in cases],
        "all_present": all_present,
        "output_token_override": max_output_tokens,
        "max_logical_calls": sum(
            (case.population if all_present else case.active) + 6 for case in cases
        ),
        "token_cost": "Unknown until measured; logical call bounds exclude transport retries.",
        "rubrics": {key: value[1] for key, value in matrix_cases.SITUATIONS.items()},
        "history": "Authored fixture speech, not model-generated prehistory. Each case records its history length and whether events are daily or two minutes apart.",
        "current_events": "Only explicit author-assigned public test events enter cognition as world observations. Feelings are not supplied as external facts.",
        "review": [
            "Trace decision changes to personal motives and observed sources.",
            "Compare characters' choices, not just wording or warmth.",
            "Check candidate alternatives are meaningfully different; exact-duplicate metric alone is insufficient.",
            "Separate temporary affect, local relationships and tentative trait tendencies.",
            "Useful contextual questions are allowed; permission to keep speaking is not a required information gap.",
            "No single-model pass proves accurate human psychology.",
        ],
    }


async def execute(args: argparse.Namespace, cases: list[matrix_cases.MatrixCase]) -> None:
    output_limit = getattr(args, "output_tokens", None)
    plan = manifest(cases, all_present=args.all_present, max_output_tokens=output_limit)
    if plan["max_logical_calls"] > args.max_total_calls:
        raise ValueError(
            f"Plan needs up to {plan['max_logical_calls']} logical calls; quota is {args.max_total_calls}."
        )
    from backend.engine.chpm.evaluation import storage

    # Validate output and quota before discovery or any other network operation.
    folder = storage.create(args.run_id, plan)
    from backend.engine.chpm.evaluation.configuration import factory_for
    from backend.engine.chpm.evaluation.matrix_runner import run

    factory = await factory_for(
        args.user, args.endpoint, args.model, max_output_tokens=output_limit
    )
    completed = 0
    calls = 0
    for case in cases:
        result = await run(
            case,
            factory,
            all_present=args.all_present,
            timeout=args.timeout,
            max_output_tokens=output_limit,
        )
        calls += len(result["calls"])
        target = storage.path(folder, "results.jsonl")
        line = json.dumps(result, ensure_ascii=False) + "\n"
        if target.stat().st_size + len(line.encode("utf-8")) > storage.MAX_BYTES:
            raise ValueError("Matrix artifact limit reached; earlier results were retained.")
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line)
        completed += 1
        print(f"{case.id}: {result['status']}; cumulative calls={calls}", flush=True)
        if any(call["status"] != "ok" for call in result["calls"]):
            print(
                "Stopped after an incomplete request. Verify remote completion before another run.",
                flush=True,
            )
            break
    storage.path(folder, "summary.json").write_text(
        json.dumps(
            {
                "completed": completed,
                "planned": len(cases),
                "calls": calls,
                "psychological_ratings": "pending manual review; inspect failed cases separately",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "run"))
    parser.add_argument(
        "--suite", choices=("smoke", "large", "full", "stress", "continuity"), default="smoke"
    )
    parser.add_argument(
        "--output-tokens",
        type=int,
        choices=range(512, 8193),
        help="Explicit CHPM output limit; also sets temporary endpoint role limits. Saved role limits still apply with --user.",
    )
    parser.add_argument("--case", action="append", default=[], dest="cases")
    parser.add_argument("--all-present", action="store_true")
    parser.add_argument("--max-total-calls", type=int, default=0)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--endpoint")
    source.add_argument("--user")
    parser.add_argument("--model")
    parser.add_argument("--run-id")
    parser.add_argument("--timeout", type=int, choices=range(10, 601), default=120)
    args = parser.parse_args()
    cases = matrix_cases.choose(args.suite, args.cases)
    if args.action == "plan":
        print(
            json.dumps(
                manifest(cases, all_present=args.all_present, max_output_tokens=args.output_tokens),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not args.run_id or not (args.endpoint or args.user) or args.max_total_calls < 1:
        parser.error("run requires --run-id, --endpoint or --user, and --max-total-calls")
    asyncio.run(execute(args, cases))


if __name__ == "__main__":
    main()
