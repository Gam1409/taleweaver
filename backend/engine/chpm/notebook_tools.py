"""Private staged notebook capability; no database or world-state mutations."""

from dataclasses import dataclass, field
from hashlib import sha256

from backend.engine.chpm.agent_contracts import Lookup
from backend.engine.chpm.notebook.codec import MAX_BYTES, NotebookError
from backend.engine.chpm.notebook.workspace import NotebookWorkspace
from backend.engine.chpm.notebook_requests import (
    NotebookDelete,
    NotebookEdit,
    NotebookInfo,
    NotebookRead,
    NotebookRequest,
    NotebookWrite,
)


@dataclass
class NotebookDraft:
    workspace: NotebookWorkspace
    committable: bool = True
    reads: list[dict] = field(default_factory=list)

    def metadata(self) -> dict:
        return {
            "status": "available",
            "revision": self.workspace.revision,
            "used_bytes": self.workspace.byte_size,
            "limit_bytes": MAX_BYTES,
            "remaining_bytes": MAX_BYTES - self.workspace.byte_size,
        }

    def execute(self, request: NotebookRequest) -> dict:
        try:
            return self._execute(request)
        except NotebookError as exc:
            return {"status": exc.code, "message": str(exc), "revision": self.workspace.revision}

    def _execute(self, request: NotebookRequest) -> dict:
        if isinstance(request, NotebookInfo):
            return self.metadata()
        if isinstance(request, NotebookRead):
            result = self.workspace.read(request.path, offset=request.offset, limit=request.limit)
            self.reads = [*self.reads, result][-4:]
            return result
        if isinstance(request, NotebookWrite):
            return self.workspace.write(
                request.path, request.value_json, expected_revision=request.expected_revision
            )
        if isinstance(request, NotebookDelete):
            return self.workspace.delete(request.path, expected_revision=request.expected_revision)
        if isinstance(request, NotebookEdit):
            return self.workspace.edit(
                [operation.model_dump(exclude_none=True) for operation in request.operations],
                expected_revision=request.expected_revision,
            )
        raise NotebookError("invalid_tool", "Unknown personal notebook operation.")

    def context(self) -> dict:
        return {
            **self.metadata(),
            "meaning": "self_authored_subjective_notes_not_world_evidence",
            "selected_reads": list(self.reads),
            "pending_changes": self.committable and self.workspace.changed,
        }


def request_summary(request: Lookup | NotebookRequest) -> dict:
    field = "argument" if isinstance(request, Lookup) else "path"
    value = getattr(request, field, "")
    result: dict = {"tool": request.tool, f"{field}_hash": sha256(value.encode()).hexdigest()}
    if isinstance(request, NotebookEdit):
        result["operation_count"] = len(request.operations)
    return result


def result_summary(result: dict) -> dict:
    return {
        key: value
        for key, value in result.items()
        if key in {"status", "revision", "byte_size", "used_bytes", "remaining_bytes", "changed"}
    }


def packed_context(value: dict, tier: int) -> dict:
    """Reduce only the transient view; the one stored notebook is never trimmed."""
    reads = value.get("selected_reads", [])
    count = (4, 2, 1, 0)[min(tier, 3)]
    kept = reads[-count:] if count else []
    return {**value, "selected_reads": kept, "omitted_reads": len(reads) - len(kept)}
