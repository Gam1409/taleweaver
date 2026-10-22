"""Compact validation summary for the world generation log.

The generation view renders entries of type ``validation`` as a short result
card, so the payload stays deliberately small: counts plus a handful of the
findings that were auto-fixed and that are still open.
"""

import datetime
from typing import TYPE_CHECKING, Any, Optional

from backend.models.adventure_template import AdventureTemplate

if TYPE_CHECKING:
    from backend.api.routes.adventures.editing.auto_fix import AutoFixReport
    from backend.schemas.validation import ValidationFinding

# Only the top fixed/open findings are listed; the rest live in the editor's Validation tab.
MAX_LOGGED_FINDINGS = 5
_MAX_MESSAGE_LENGTH = 140


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _shorten(text: str) -> str:
    if len(text) <= _MAX_MESSAGE_LENGTH:
        return text
    return text[: _MAX_MESSAGE_LENGTH - 1].rstrip() + "…"


def summarize_report(report: "AutoFixReport") -> str:
    """One-line summary, e.g. '4 findings (1 error, 3 warnings) · 3 auto-fixed · 1 open'."""
    if report.findings_total == 0:
        return "No issues found"
    parts = [_plural(report.errors, "error"), _plural(report.warnings, "warning")]
    return (
        f"{_plural(report.findings_total, 'finding')} ({', '.join(parts)})"
        f" · {report.fixed} auto-fixed · {report.remaining} open"
    )


def build_validation_log_entry(
    report: Optional["AutoFixReport"], failure: Optional[str] = None
) -> dict[str, Any]:
    """Build a ``validation`` generation-log entry from an auto-fix report or a failure."""
    entry: dict[str, Any] = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "type": "validation",
    }
    if report is None:
        entry["content"] = f"Validation could not complete: {failure or 'unknown error'}"
        entry["details"] = {"failed": True}
        return entry

    entry["content"] = summarize_report(report)
    entry["details"] = {
        "findings_total": report.findings_total,
        "errors": report.errors,
        "warnings": report.warnings,
        "fixed": report.fixed,
        "remaining": report.remaining,
        "ai_skipped_reason": report.ai_skipped_reason,
        "fixed_findings": _compact(report.resolved),
        "open_findings": _compact(report.unresolved),
    }
    return entry


def _compact(findings: list["ValidationFinding"]) -> list[dict[str, Any]]:
    return [
        {
            "severity": finding.severity,
            "message": _shorten(finding.message),
            "location": finding.location,
        }
        for finding in findings[:MAX_LOGGED_FINDINGS]
    ]


def append_validation_log(adventure: AdventureTemplate, entry: dict[str, Any]) -> None:
    """Append the entry to the template's generation log (caller commits)."""
    logs = list(adventure.generation_logs or [])
    logs.append(entry)
    adventure.generation_logs = logs  # type: ignore[assignment]
