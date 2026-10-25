"""Durable checkpoints kept separate from the playable world manifest."""

import hashlib
import json
from copy import deepcopy
from typing import Any

from sqlalchemy.orm.attributes import set_committed_value

from backend.engine.generation_control import guard_generation_write
from backend.models.adventure_template import AdventureTemplate

VERSION = 1


def input_fingerprint(system: str, user: str, metadata: dict, mode: str | None) -> str:
    payload = json.dumps(
        [VERSION, system, user, metadata, mode], sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class Checkpoints:
    def __init__(self, db: Any, adventure: AdventureTemplate | None, fingerprint: str):
        self.db = db
        self.adventure = adventure
        saved = (getattr(adventure, "generation_checkpoint", None) or {}) if adventure else {}
        self.data = (
            deepcopy(saved)
            if saved.get("version") == VERSION and saved.get("fingerprint") == fingerprint
            else {"version": VERSION, "fingerprint": fingerprint, "results": {}}
        )

    @property
    def results(self) -> dict:
        return self.data["results"]

    async def check(self) -> None:
        if self.adventure is None:
            return
        from backend.engine.generation_control import assert_generation_current

        await assert_generation_current(self.db, self.adventure)

    async def save(self, key: str, result: dict, elapsed: float) -> None:
        await self.check()
        self.results[key] = deepcopy(result)
        self.data.setdefault("timings", {})[key] = round(elapsed, 2)
        await self.flush()

    async def invalidate(self, keys: list[str]) -> None:
        await self.check()
        for key in keys:
            self.results.pop(key, None)
        await self.flush()

    async def flush(self) -> None:
        if self.adventure is None:
            return
        await guard_generation_write(
            self.db, self.adventure, generation_checkpoint=deepcopy(self.data)
        )
        await self.db.commit()
        set_committed_value(self.adventure, "generation_checkpoint", deepcopy(self.data))
