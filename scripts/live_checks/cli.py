"""No-network planning; paid execution requires an endpoint and an explicit quota."""

import argparse
import importlib
import importlib.metadata
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .catalog import GROUPS, manifest, select

ROOT = Path(__file__).resolve().parents[2]
DEPENDENCIES = (
    "pytest",
    "pytest_asyncio",
    "sqlalchemy",
    "cryptography",
    "uuid6",
    "lancedb",
    "pyarrow",
)


def review(args: argparse.Namespace) -> int:
    from cryptography.fernet import Fernet

    os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(48))
    os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
    from .review import review_run

    if not args.run_id:
        raise ValueError("review requires --run-id.")
    return review_run(args.run_id)


def preflight() -> dict:
    versions, missing = {}, []
    for name in DEPENDENCIES:
        try:
            importlib.import_module(name)
            versions[name] = importlib.metadata.version(name.replace("_", "-"))
        except (ImportError, importlib.metadata.PackageNotFoundError):
            missing.append(name)
    return {
        "ready": not missing and (3, 11) <= sys.version_info[:2] < (3, 14),
        "python": sys.version.split()[0],
        "versions": versions,
        "missing": missing,
        "remedy": "Run poetry install and use poetry run python from the source checkout.",
    }


def endpoint(value: str) -> str:
    value = value.strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use a credential-free HTTP(S) API URL without query or fragment.")
    base = value.rstrip("/")
    if base.endswith("/chat/completions"):
        base = base.removesuffix("/chat/completions")
    return base if base.endswith("/v1") else base + "/v1"


def bounded(value: str, minimum: int, maximum: int) -> int:
    number = int(value)
    if not minimum <= number <= maximum:
        raise argparse.ArgumentTypeError(f"Use an integer between {minimum} and {maximum}.")
    return number


def _environment(args: argparse.Namespace, plan: dict, directory: str) -> dict:
    from cryptography.fernet import Fernet

    values = dict(os.environ)
    for name in tuple(values):
        if name.endswith("_API_KEY") and name != "TALEWEAVER_LIVE_API_KEY":
            values.pop(name)
    values.update(
        {
            "SECRET_KEY": secrets.token_urlsafe(48),
            "ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "DATA_DIR": str(Path(directory) / "data"),
            "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "MEMORY_DB_DIR": str(Path(directory) / "memory"),
            "INFERENCE_SERIALIZATION_ENABLED": "true",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "TALEWEAVER_LIVE_ENABLED": "explicit-run",
            "TALEWEAVER_LIVE_ENDPOINT": endpoint(args.endpoint),
            "TALEWEAVER_LIVE_MODEL": args.model or "",
            "TALEWEAVER_LIVE_RUN_ID": args.run_id,
            "TALEWEAVER_LIVE_CASES": json.dumps([case["id"] for case in plan["cases"]]),
            "TALEWEAVER_LIVE_REPETITIONS": str(args.repetitions),
            "TALEWEAVER_LIVE_MAX_CALLS": str(args.max_calls),
            "TALEWEAVER_LIVE_OUTPUT_TOKENS": str(args.output_tokens),
            "TALEWEAVER_LIVE_TIMEOUT": str(args.timeout),
            "TALEWEAVER_LIVE_MANIFEST": json.dumps(plan),
        }
    )
    return values


def execute(args: argparse.Namespace, plan: dict) -> int:
    if not args.endpoint or not args.run_id or args.max_calls < 1:
        raise ValueError("run requires --endpoint, --run-id and a positive --max-calls.")
    endpoint(args.endpoint)
    if not args.run_id.isascii() or not args.run_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Use an ASCII run ID containing letters, digits, hyphens or underscores.")
    if len(args.run_id) > 80:
        raise ValueError("Run ID exceeds 80 characters.")
    status = preflight()
    if not status["ready"]:
        print(json.dumps(status, indent=2))
        return 2
    plan["engine_revision"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    plan["working_tree_dirty"] = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    plan["gateway_quota"] = args.max_calls
    plan["output_token_limit"] = args.output_tokens
    plan["provider_timeout_seconds"] = args.timeout
    with tempfile.TemporaryDirectory(prefix="taleweaver-live-") as directory:
        values = _environment(args, plan, directory)
        command = [
            sys.executable,
            "-m",
            "pytest",
            "tests/live_contracts.py",
            "-q",
            "--tb=short",
            "-s",
        ]
        collected = subprocess.run(command + ["--collect-only"], cwd=ROOT, env=values, check=False)
        if collected.returncode:
            return collected.returncode
        result = subprocess.run(command, cwd=ROOT, env=values, check=False)
    try:
        review(args)
    except ValueError as exc:
        print(str(exc))
    return result.returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "preflight", "run", "review"))
    parser.add_argument("--group", action="append", choices=GROUPS, default=[])
    parser.add_argument("--case", action="append", default=[], dest="cases")
    parser.add_argument("--repetitions", type=int, choices=range(1, 21), default=1)
    parser.add_argument("--endpoint")
    parser.add_argument("--model")
    parser.add_argument("--run-id")
    parser.add_argument("--max-calls", type=int, default=0)
    parser.add_argument(
        "--output-tokens", type=lambda value: bounded(value, 512, 8192), default=4096
    )
    parser.add_argument("--timeout", type=lambda value: bounded(value, 10, 600), default=180)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "preflight":
            status = preflight()
            print(json.dumps(status, indent=2))
            return 0 if status["ready"] else 2
        plan = manifest(select(args.group, args.cases), args.repetitions)
        if args.action == "plan":
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        if args.action == "review":
            return review(args)
        return execute(args, plan)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 2
