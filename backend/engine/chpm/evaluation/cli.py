"""Plan without inference; run only on an explicit operator command."""

import argparse
import asyncio
import json
from uuid import uuid4

from backend.engine.chpm.evaluation.cases import VERSION, choose
from backend.engine.chpm.evaluation.contracts import Arm
from backend.engine.chpm.schema import Settings


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="Isolated CHPM dialogue comparison (synthetic scenes only)."
    )
    actions = command.add_subparsers(dest="action", required=True)
    for name in ("plan", "run", "probe"):
        child = actions.add_parser(name)
        child.add_argument("--case", action="append", default=[], dest="cases")
        if name != "probe":
            child.add_argument("--repeats", type=int, choices=range(1, 21), default=1)
            child.add_argument("--role", choices=("small", "complex"), default="complex")
            child.add_argument("--calls", type=int, choices=range(3, 9), default=6)
        child.add_argument("--timeout", type=int, choices=range(10, 601), default=120)
        if name in {"run", "probe"}:
            source = child.add_mutually_exclusive_group(required=True)
            source.add_argument(
                "--user", help="Existing account whose model configurations to use."
            )
            source.add_argument(
                "--endpoint",
                help="Temporary OpenAI-compatible /v1 URL; no saved settings are changed.",
            )
            child.add_argument(
                "--model", help="Model ID for --endpoint; otherwise discover its single model."
            )
            child.add_argument(
                "--run-id",
                required=True,
                help="New private log directory name; existing runs are never overwritten.",
            )
        if name == "probe":
            child.add_argument(
                "--violation",
                choices=("takeover", "promise", "completed_action"),
                default="takeover",
            )
            child.add_argument(
                "--source-run",
                required=True,
                help="Existing run with an accepted CHPM reply for --case.",
            )
    report = actions.add_parser("report")
    report.add_argument("--run-id", required=True)
    return command


def plan(args: argparse.Namespace) -> dict:
    selected = choose(args.cases)
    return {
        "suite": VERSION,
        "cases": [case.id for case in selected],
        "repeats": args.repeats,
        "pairs": len(selected) * args.repeats,
        "max_logical_calls": len(selected) * args.repeats * (args.calls + 2),
        "role": args.role,
        "narrator_role": "complex",
        "repair_role": "complex",
        "calls_per_chpm_arm": args.calls,
        "timeout_seconds_per_call": args.timeout,
        "token_cost": "Unknown until the provider reports usage. Transport retries may add cost.",
        "scope": "Isolated dialogue comparison; not full VN or Concordia performance.",
    }


def _source_fingerprint() -> str:
    import inspect

    from backend.engine.chpm import (
        cognition,
        context,
        inference,
        json_contract,
        kernel,
        passages,
        perception,
        prompts,
        rendering,
        schema,
    )
    from backend.engine.chpm.evaluation import (
        cases,
        character_stress,
        long_context,
        personas,
        port,
        runner,
        stress_cases,
    )

    modules = (
        cognition,
        context,
        inference,
        json_contract,
        kernel,
        passages,
        perception,
        prompts,
        rendering,
        schema,
        cases,
        port,
        runner,
        character_stress,
        long_context,
        personas,
        stress_cases,
    )
    return kernel.fingerprint({module.__name__: inspect.getsource(module) for module in modules})


async def run(args: argparse.Namespace) -> None:
    # Imports stay here so planning works without credentials, a database or a GPU.
    from backend.engine.chpm.evaluation import storage
    from backend.engine.chpm.evaluation.configuration import factory_for
    from backend.engine.chpm.evaluation.runner import run_arm
    from backend.engine.chpm.kernel import digest

    selected = choose(args.cases)
    prefs = Settings(
        mode="live", actor_ids=["npc"], model_role=args.role, max_calls_per_turn=args.calls
    )
    if args.model and not args.endpoint:
        raise ValueError("--model is only used with --endpoint.")
    factory = await factory_for(args.user, args.endpoint, args.model)
    seed = uuid4().hex
    manifest = {
        **plan(args),
        "cases": [case.model_dump() for case in selected],
        "settings": prefs.model_dump(),
        "blind_seed": seed,
        "source_fingerprint": _source_fingerprint(),
    }
    folder = storage.create(args.run_id, manifest)
    print(json.dumps(plan(args), ensure_ascii=False, indent=2))
    print(f"Writing private evaluation artifacts to {folder}")
    try:
        for index in range(len(selected) * args.repeats):
            case = selected[index // args.repeats]
            repetition = index % args.repeats + 1
            arms: tuple[Arm, Arm] = ("baseline", "chpm") if index % 2 == 0 else ("chpm", "baseline")
            for arm in arms:
                result = await run_arm(
                    case,
                    repetition,
                    arm,
                    factory,
                    prefs,
                    timeout=args.timeout,
                )
                storage.append(folder, result)
                print(
                    f"{case.id} repeat {repetition} {arm}: {result.status}, {len(result.calls)} logical calls"
                )
    finally:
        storage.finish(folder)
    # Do not print the blind key or any user/model configuration credentials.
    print(
        f"Run fingerprint: {digest(seed)[:12]}. Read review.md, fill ratings.jsonl, then run report."
    )


async def control_probe(args: argparse.Namespace) -> None:
    from backend.engine.chpm.evaluation import control, storage
    from backend.engine.chpm.evaluation.configuration import factory_for
    from backend.engine.chpm.kernel import digest

    if args.model and not args.endpoint:
        raise ValueError("--model is only used with --endpoint.")
    if len(args.cases) != 1:
        raise ValueError("Specify exactly one --case for the control probe.")
    manifest, cases, results = storage.load(storage.directory(args.source_run))
    case = next((item for item in cases if item.id == args.cases[0]), None)
    source = next(
        (
            item
            for item in results
            if item.case_id == args.cases[0] and item.arm == "chpm" and item.status == "ok"
        ),
        None,
    )
    if case is None or source is None:
        raise ValueError("No accepted CHPM reply exists for the selected source case.")
    factory = await factory_for(args.user, args.endpoint, args.model)
    folder = storage.create(
        args.run_id,
        {
            "source_run": args.source_run,
            "source_pair_id": source.pair_id,
            "source_response_hash": digest(source.response),
            "timeout_seconds_per_call": args.timeout,
            "violation_kind": args.violation,
            "case": case.model_dump(),
            "source_fingerprint": _source_fingerprint(),
        },
    )
    result = await control.probe(
        case,
        source,
        factory,
        Settings.model_validate(manifest["settings"]),
        timeout=args.timeout,
        violation_kind=args.violation,
    )
    storage.path(folder, "control.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    storage.path(folder, "control.md").write_text(control.markdown(result), encoding="utf-8")
    print(
        f"Control probe saved to {folder}. Initial review matches: {result['first_review_matches']}; injected text would publish: {result['injected_text_would_be_published']}."
    )


def main(argv: list[str] | None = None) -> int:
    command = parser()
    args = command.parse_args(argv)
    try:
        if args.action == "plan":
            print(json.dumps(plan(args), ensure_ascii=False, indent=2))
        elif args.action == "run":
            asyncio.run(run(args))
        elif args.action == "probe":
            asyncio.run(control_probe(args))
        else:
            from backend.engine.chpm.evaluation.storage import directory, report

            print(report(directory(args.run_id)))
    except KeyboardInterrupt:
        print("Evaluation interrupted. Completed arm records remain in the run directory.")
        return 130
    except (ValueError, OSError, KeyError) as exc:
        # Avoid printing provider configuration or database URLs from raw errors.
        print(f"Evaluation stopped ({type(exc).__name__}). Check arguments and private artifacts.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
