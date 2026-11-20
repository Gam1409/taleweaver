"""Interpret validated property requests without reading or mutating owner storage."""

from typing import Literal

from backend.engine.npc_actions.contracts import ChangeState, Use


def requested_property(request: ChangeState | Use) -> tuple[str, str, Literal["public", "private"]]:
    if isinstance(request, ChangeState):
        return request.dimension, request.detail, request.visibility
    detail = request.remaining_detail or (
        "Used completely." if request.extent == "full" else "Used partly."
    )
    return "usage", detail, "public"
