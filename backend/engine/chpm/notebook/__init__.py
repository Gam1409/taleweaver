"""Pure JSON notebook operations, detached from host persistence and tool routing."""

from backend.engine.chpm.notebook.codec import (
    MAX_BYTES,
    MAX_DEPTH,
    MAX_NODES,
    JsonValue,
    NotebookError,
    canonicalize,
    decode,
    encode,
    preflight,
)
from backend.engine.chpm.notebook.workspace import NotebookWorkspace

__all__ = [
    "MAX_BYTES",
    "MAX_DEPTH",
    "MAX_NODES",
    "JsonValue",
    "NotebookError",
    "NotebookWorkspace",
    "canonicalize",
    "decode",
    "encode",
    "preflight",
]
