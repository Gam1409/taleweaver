"""Preview or write an upstream-compatible ADZ copy; never uploads or pushes files."""

import argparse
import json
import sys
from pathlib import Path

# Support direct execution as well as python -m scripts.prepare_adventure_publication.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.adventure_publication import PublicationError, prepare_bundle
from backend.services.adventure_publication.bundle import MAX_BUNDLE_BYTES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "adventure", type=Path, help="Exported adventure .adz (not a saved session)"
    )
    parser.add_argument(
        "--output", type=Path, help="Write converted ADZ; omitted means preview only"
    )
    parser.add_argument(
        "--acknowledge-changes", action="store_true", help="Accept reported compatibility changes"
    )
    args = parser.parse_args(argv)
    try:
        if args.adventure.stat().st_size > MAX_BUNDLE_BYTES:
            raise PublicationError("Input exceeds the 100 MiB limit.")
        data, report = prepare_bundle(args.adventure.read_bytes())
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.output is None:
            return 0
        if report["requires_acknowledgement"] and not args.acknowledge_changes:
            raise PublicationError(
                "Preview the report and pass --acknowledge-changes to accept conversion."
            )
        # Exclusive creation prevents overwriting the source or an existing publication.
        with args.output.open("xb") as output:
            output.write(data)
        return 0
    except (OSError, PublicationError) as exc:
        print(f"Publication preparation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
