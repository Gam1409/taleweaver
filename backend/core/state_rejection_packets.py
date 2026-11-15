"""Isolate independent failing check subtrees without slicing their captured evidence."""

from uuid import uuid4

MAX_STEPS = 2048
MAX_STEP_DEPTH = 64
_TURN_EVENTS = frozenset(
    {"detail.engine.turn.started", "detail.engine.turn.ended", "detail.engine.event"}
)


class _UnsafeGraphError(ValueError):
    """A fixed host reason for preserving the complete capture."""


def _rejections(rows: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for row in rows:
        if row.get("event") != "state.rejected":
            continue
        group = row.get("detail_group")
        if group is not None and group in seen:
            continue
        if group is not None:
            seen.add(group)
        result.append(row)
    return result


def _graph(rows: list[dict]) -> dict[str, frozenset[str]]:
    parents: dict[str, str | None] = {}
    for row in rows:
        key = row.get("step_id")
        if not isinstance(key, str):
            continue
        parent = row.get("parent_step_id")
        if parent is not None and not isinstance(parent, str):
            raise _UnsafeGraphError("ambiguous_step_graph")
        if key in parents and parents[key] != parent:
            raise _UnsafeGraphError("ambiguous_step_graph")
        parents[key] = parent
        if len(parents) > MAX_STEPS:
            raise _UnsafeGraphError("step_graph_limit")
    graph = {}
    for key in parents:
        path: set[str] = set()
        current: str | None = key
        while isinstance(current, str):
            if current in path:
                raise _UnsafeGraphError("ambiguous_step_graph")
            if len(path) >= MAX_STEP_DEPTH:
                raise _UnsafeGraphError("step_graph_limit")
            path.add(current)
            current = parents.get(current)
        graph[key] = frozenset(path)
    return graph


def _shared(row: dict) -> bool:
    event = row.get("event")
    if not isinstance(event, str):
        return False
    return event in _TURN_EVENTS or (row.get("step_id") is None and not event.startswith("detail."))


def _fallback(rows: list[dict], reason: str) -> list[list[dict]]:
    footer = {**rows[-1], "packet_isolation": {"status": "unavailable", "reason": reason}}
    return [[*rows[:-1], footer]]


def _belongs(row: dict, root: str, graph: dict[str, frozenset[str]]) -> bool:
    key = row.get("step_id")
    return isinstance(key, str) and root in graph.get(key, ())


def split(rows: list[dict]) -> list[list[dict]]:
    """Keep unknown/overflowed captures whole rather than inventing safe boundaries."""
    header, footer = rows[0], rows[-1]
    body = rows[1:-1]
    if footer.get("capture_overflow", {}).get("omitted_events", 0):
        return _fallback(rows, "capture_overflow")
    rejected = _rejections(body)
    if len(rejected) != footer.get("rejected_count"):
        return _fallback(rows, "incomplete_rejections")
    if any(not isinstance(row.get("step_id"), str) for row in rejected):
        return _fallback(rows, "unscoped_failure")
    try:
        graph = _graph(body)
    except _UnsafeGraphError as exc:
        return _fallback(rows, str(exc))
    failed = {row["step_id"] for row in rejected}
    roots = list(
        dict.fromkeys(
            row["step_id"]
            for row in rejected
            if not (graph[row["step_id"]] - {row["step_id"]}) & failed
        )
    )
    if not roots:
        return _fallback(rows, "ambiguous_step_graph")
    return [_packet(header, footer, body, rejected, graph, root, len(roots)) for root in roots]


def _packet(
    header: dict,
    footer: dict,
    body: list[dict],
    rejected: list[dict],
    graph: dict[str, frozenset[str]],
    root: str,
    total_packets: int,
) -> list[dict]:
    identity = uuid4().hex
    indices = [index for index, row in enumerate(rejected) if root in graph[row["step_id"]]]
    summaries = footer.get("rejection_summaries", [])
    selected_summaries = [summaries[index] for index in indices if index < len(summaries)]
    return [
        {
            **header,
            "trace_id": identity,
            "parent_trace_id": header["trace_id"],
            "failure_step_id": root,
        },
        *[row for row in body if _belongs(row, root, graph) or _shared(row)],
        {
            **footer,
            "trace_id": identity,
            "rejected_count": len(indices),
            "rejection_summaries": selected_summaries,
            "omitted_rejection_summaries": len(indices) - len(selected_summaries),
            "packet_isolation": {
                "status": "isolated",
                "source_rejected_count": len(rejected),
                "related_packets": total_packets,
            },
        },
    ]
