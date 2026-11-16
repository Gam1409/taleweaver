"""Short turn transactions backed by a durable recovery snapshot.

The session mutation lease remains held while model calls run. A normal turn's
recovery snapshot includes its submitted input but precedes model-driven changes.
Replay already has its own durable backup. Only these recoverable turns may
publish intermediate mechanics before narration completes.
"""

from typing import Any

from backend.engine.turn_replay.snapshot import capture
from backend.models.turn_replay import TurnReplay


async def release_for_model(manager: Any) -> None:
    if getattr(manager, "_replaying", False):
        await manager.db.commit()
        return
    if not getattr(manager, "_turn_replay_recorded", False):
        return
    row = await manager.db.get(TurnReplay, manager.game_id)
    if row is None:
        raise RuntimeError("The turn recovery record is missing")
    if row.status == "pending":
        row.backup = await capture(manager.db, manager.game_id)
        row.status = "executing"
        manager._recoverable_turn = True
    await manager.db.commit()
