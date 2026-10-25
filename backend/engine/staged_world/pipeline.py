"""Plan once, fill small batches, validate, then hand off to world persistence."""

import json
import logging
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from backend.core.game_modes import mode_policy
from backend.engine.staged_world.checkpoints import Checkpoints, input_fingerprint
from backend.engine.staged_world.constraints import validate_constraints
from backend.engine.staged_world.prompts import DETAIL_INSTRUCTION, PLAN_INSTRUCTION, detail_context
from backend.engine.staged_world.schemas import (
    DETAIL_SCHEMAS,
    ProtagonistDetail,
    WorldPlan,
    batch_schema,
)
from backend.engine.staged_world.validation import validate_batch, validate_manifest, validate_plan
from backend.engine.vn_world_generation import normalize_vn_generated_manifest
from backend.engine.world_schemas import WorldManifesto

logger = logging.getLogger(__name__)
Status = Callable[[str], Awaitable[None]]


class StagedGeneration:
    def __init__(
        self,
        *,
        llm: Any,
        store: Checkpoints,
        system: str,
        user: str,
        metadata: dict,
        mode: str | None,
        status: Status,
        template_id: str,
    ):
        self.llm = llm
        self.store = store
        self.system = system
        self.user = user
        self.metadata = metadata
        self.mode = mode
        self.status = status
        self.template_id = template_id

    async def request(
        self,
        key: str,
        schema: type[BaseModel],
        prompt: str,
        instruction: str,
        validate: Callable[[dict], None],
    ) -> dict:
        await self.store.check()
        if key in self.store.results:
            try:
                cached = schema.model_validate(deepcopy(self.store.results[key])).model_dump()
                validate(cached)
                return cached
            except ValueError:
                # A replaced plan invalidates every dependent detail. A bad detail
                # affects only that batch, so valid siblings still survive.
                keys = list(self.store.results) if key == "plan" else [key]
                await self.store.invalidate(keys)
        original_budget = self.llm.max_tokens
        self.llm.max_tokens = original_budget if key == "plan" else min(original_budget, 3072)
        started = time.monotonic()
        try:
            result = await self._request_valid(key, schema, prompt, instruction, validate)
        finally:
            self.llm.max_tokens = original_budget
        await self.store.save(key, result, time.monotonic() - started)
        return result

    async def _request_valid(
        self,
        key: str,
        schema: type[BaseModel],
        prompt: str,
        instruction: str,
        validate: Callable[[dict], None],
    ) -> dict:
        correction = ""
        for attempt in range(2):
            await self.store.check()
            try:
                response = await self.llm.aexecute_complex_task(
                    system_prompt=self.system + instruction,
                    user_prompt=prompt + correction,
                    response_model=schema,
                    model=self.llm.model,
                    adventure_id=self.template_id,
                    operation="generate_world",
                    phase=key,
                    metadata={**self.metadata, "stage": key, "attempt": attempt + 1},
                )
                await self.store.check()
                result = response.model_dump()
                validate(result)
                return result
            except ValueError as exc:
                logger.warning("World generation stage %s failed validation: %s", key, exc)
                correction = (
                    "\nCorrect the previous invalid stage. Validation feedback:\n" + str(exc)[:1200]
                )
                if attempt == 0:
                    await self.status(f"Correcting {key}; completed stages are saved")
        raise ValueError(
            f"World generation stage '{key}' returned invalid data twice. "
            "Completed stages are saved. Resume generation to retry this stage; see the backend log."
        )

    def check_plan(self, plan: dict) -> None:
        validate_plan(plan)
        validate_constraints(plan, self.metadata, self.mode)

    async def run(self) -> WorldManifesto:
        await self.store.check()
        await self.store.flush()
        await self.status("Planning story and world connections (stage 1)")
        planning_prompt = (
            self.user
            + "\nGeneration constraints:\n"
            + json.dumps({"mode": self.mode, **self.metadata}, ensure_ascii=False)
        )
        plan = await self.request(
            "plan", WorldPlan, planning_prompt, PLAN_INSTRUCTION, self.check_plan
        )
        total = 2 + sum((len(plan[k]) + 1) // 2 for k in DETAIL_SCHEMAS)
        await self.status(f"Developing protagonist (stage 2/{total})")
        protagonist = await self.detail(plan, "protagonist", [plan["protagonist"]], "protagonist")
        manifest = {**deepcopy(plan["foundation"]), "exits": deepcopy(plan["exits"]), **protagonist}
        stage = 2
        for kind in DETAIL_SCHEMAS:
            manifest[kind] = []
            for start in range(0, len(plan[kind]), 2):
                stage += 1
                end = min(start + 2, len(plan[kind]))
                await self.status(
                    f"Developing {kind} {start + 1}-{end}/{len(plan[kind])} (stage {stage}/{total})"
                )
                result = await self.detail(plan, kind, plan[kind][start:end], f"{kind}:{start}")
                manifest[kind].extend(result["items"])
        await self.status("Checking world references and ownership")
        if mode_policy(self.mode).vn:
            normalize_vn_generated_manifest(manifest)
        validate_manifest(manifest, plan)
        return WorldManifesto.model_validate(manifest)

    async def detail(self, plan: dict, kind: str, seeds: list[dict], key: str) -> dict:
        schema = ProtagonistDetail if kind == "protagonist" else batch_schema(kind)

        def validate(result: dict) -> None:
            rows = [result["protagonist"]] if kind == "protagonist" else result["items"]
            if kind != "protagonist":
                id_field = "key" if kind == "awards" else "id"
                if sorted(row[id_field] for row in rows) != sorted(seed["id"] for seed in seeds):
                    raise ValueError(
                        "Return exactly the requested IDs, with no omissions or additions."
                    )
                ordering = {seed["id"]: index for index, seed in enumerate(seeds)}
                rows.sort(key=lambda row: ordering[row[id_field]])
            _bind_ownership(kind, rows, plan)
            validate_batch(kind, rows, plan)

        return await self.request(
            key,
            schema,
            self.user + "\n" + detail_context(plan, kind, seeds, self.store.results),
            DETAIL_INSTRUCTION,
            validate,
        )


def _bind_ownership(kind: str, rows: list[dict], plan: dict) -> None:
    """Ownership is decided once, never independently invented by detail stages."""
    if kind not in {"protagonist", "npcs", "objects"}:
        return
    for row in rows:
        owner = "PROTAGONIST" if kind == "protagonist" else row["id"]
        field = "starting_inventory" if kind == "protagonist" else "inventory"
        row[field] = [item["id"] for item in plan["objects"] if item.get("owner_id") == owner]


async def generate_manifest(
    *,
    db: Any,
    adventure: Any,
    llm: Any,
    system_prompt: str,
    user_prompt: str,
    metadata: dict,
    mode: str | None,
    status: Status,
    template_id: str,
) -> WorldManifesto:
    store = Checkpoints(
        db, adventure, input_fingerprint(system_prompt, user_prompt, metadata, mode)
    )
    runner = StagedGeneration(
        llm=llm,
        store=store,
        system=system_prompt,
        user=user_prompt,
        metadata=metadata,
        mode=mode,
        status=status,
        template_id=template_id,
    )
    return await runner.run()
