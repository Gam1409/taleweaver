"""Pure DTO projections; callers load and verify session ownership in SQL."""

from typing import Any

from backend.engine.world_info import limits
from backend.engine.world_info.schemas import EntryDetail, EntrySummary, Job, SourceView
from backend.engine.world_info.types import EntryDraft, searchable_text
from backend.models.world_info import WorldInfoEntry, WorldInfoRevision, WorldInfoSource


class ViewNotFoundError(LookupError):
    """A requested record is unavailable in the selected session."""


class ViewIntegrityError(ValueError):
    """Saved metadata could not be projected without exposing validation input."""


def job_record(revision: WorldInfoRevision, source: WorldInfoSource, sizes: tuple[int, int]) -> Job:
    current = source.current_revision == revision.number
    remaining = not revision.total_batches or revision.cursor < revision.total_batches
    compatible = (
        revision.parser_version == limits.PARSER_VERSION
        and revision.extraction_version == limits.EXTRACTION_VERSION
    )
    can_process = (
        revision.control_version < limits.MAX_COUNTER - 1
        and revision.attempts < limits.MAX_COUNTER
        and (
            not revision.total_batches
            or revision.attempts < limits.request_limit(revision.total_batches)
        )
    )
    fields = (
        "id",
        "source_id",
        "number",
        "status",
        "control_version",
        "cursor",
        "total_batches",
        "processed_characters",
        "input_bytes",
        "input_characters",
        "facts_count",
        "entries_count",
        "attempts",
        "processing_language",
    )
    code = revision.last_error_code
    if code not in {
        None,
        "inference_waiting",
        "timeout",
        "invalid_output",
        "processing_failed",
        "storage_limit",
        "request_limit",
    }:
        code = "processing_failed"
    try:
        return Job(
            **{name: getattr(revision, name) for name in fields},
            entries_characters=sizes[0],
            entries_bytes=sizes[1],
            last_error_code=code,
            request_limit=limits.request_limit(revision.total_batches)
            if revision.total_batches
            else None,
            can_start=current
            and compatible
            and can_process
            and remaining
            and revision.status == "uploaded",
            can_resume=current
            and compatible
            and can_process
            and remaining
            and revision.status in {"failed", "cancelled"},
            can_cancel=current
            and revision.control_version < limits.MAX_COUNTER
            and revision.status in {"queued", "processing"},
        )
    except ValueError:
        raise ViewIntegrityError("Saved processing metadata is invalid.") from None


def source_record(
    source: WorldInfoSource,
    revisions: list[WorldInfoRevision],
    sizes: dict[str, tuple[int, int]],
    active: int,
    draft: int,
) -> SourceView:
    current = next((row for row in revisions if row.number == source.current_revision), None)
    if current is None:
        raise ViewIntegrityError("Current source revision is unavailable.")
    try:
        return SourceView(
            **{
                key: getattr(source, key)
                for key in (
                    "id",
                    "title",
                    "filename",
                    "format",
                    "version",
                    "current_revision",
                    "published_revision",
                )
            },
            revision_count=len(revisions),
            published_revision_id=next(
                (row.id for row in revisions if row.number == source.published_revision), None
            ),
            active_entries=active,
            draft_entries=draft,
            job=job_record(current, source, sizes.get(current.id, (0, 0))),
        )
    except ValueError:
        raise ViewIntegrityError("Saved source metadata is invalid.") from None


def entry_record(
    entry: WorldInfoEntry,
    source: WorldInfoSource,
    revision: WorldInfoRevision,
    *,
    detail: bool = False,
) -> EntrySummary | EntryDetail:
    try:
        draft = EntryDraft.model_validate(
            {key: getattr(entry, key) for key in EntryDraft.model_fields}
        )
        text = searchable_text(draft)
        data: dict[str, Any] = {
            key: getattr(entry, key)
            for key in (
                "id",
                "source_id",
                "source_revision_id",
                "version",
                "title",
                "summary",
                "kind",
                "audience",
                "known_by",
                "tags",
                "status",
                "edited",
            )
        }
        data.update(
            group_name=draft.group_name,
            unresolved_known_by=getattr(entry, "unresolved_known_by", []),
            source_filename=revision.filename,
            source_revision_number=revision.number,
            is_active=entry.status == "published" and source.published_revision == revision.number,
            facts_count=len(draft.facts),
            character_count=len(text),
            byte_count=len(text.encode("utf-8")),
        )
        if detail:
            return EntryDetail(**data, facts=draft.facts, relations=draft.relations)
        return EntrySummary(**data)
    except ValueError:
        raise ViewIntegrityError("Saved entry metadata is invalid.") from None
