"""Neutral fixtures for opt-in rejection trace packets."""

import json

from backend.core.system_diagnostics import service


def isolate_trace_directory(tmp_path, monkeypatch):
    service.close()
    monkeypatch.setattr(service, "directory", tmp_path / "log")
    service.write_failed = False
    yield
    service.close()


def trace_files():
    return sorted(service.directory.glob("state-rejection-*.jsonl"))


def trace_rows(path=None):
    path = path or trace_files()[0]
    return [json.loads(line) for line in path.read_text().splitlines()]


def event_payloads(rows, event):
    selected = [row for row in rows if row["event"] == event]
    plain = [row["detail"] for row in selected if "detail" in row]
    groups = {}
    for row in selected:
        if "detail_group" in row:
            groups.setdefault(row["detail_group"], []).append(row)
    for parts in groups.values():
        parts.sort(key=lambda row: row["part"])
        plain.append(json.loads("".join(row["payload_json_part"] for row in parts)))
    return plain
