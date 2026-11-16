"""Four real gameplay turns preserve a garment across placement, transfers and washing."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.clothing.context import actor_records
from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.schema import ItemExtraction, SharedItemExtraction
from backend.engine.physical_conditions.ledger import read
from backend.engine.scene_staging import props
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.engine.visual_novel.continuity import PLAYER
from backend.engine.visual_novel.schema import InteractionPlan
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import TurnRoles, install_roles, seed_vn

ITEM = {
    "id": "RED_BRIEFS",
    "name": "Red cotton briefs",
    "description": "Plain red cotton briefs with a white stitched hem.",
    "clothing": {"layer": 0, "coverage": ["pelvis"], "opaque": True, "underwear": True},
    "wearable_slots": ["Legs"],
}
PASSAGES = [
    "Behind the closed screen, Lina lowered the red cotton briefs to her knees, leaving them partly worn. "
    "Water soaked the fabric. A blue ink stain spread across it.",
    "Lina completely removed the same red cotton briefs behind the screen. "
    "A nail tore a small hole in their left seam. Lina folded them and handed them to the hero.",
    "The hero passed the same red cotton briefs to Miki. Miki placed them inside the laundry basket on the table.",
    "Miki washed out all the blue ink and dried the red cotton briefs completely. "
    "The small hole in their left seam remained unrepaired. Behind the closed screen, Miki pulled them halfway up her thighs, leaving them partly worn.",
]


def item_action(source, destination, evidence, disposition="carried", uncovered=None):
    return {
        "item_id": ITEM["id"],
        "source_owner": source,
        "destination_owner": destination,
        "evidence": evidence,
        "basis": "completed",
        "disposition": disposition,
        "uncovered_regions": uncovered,
    }


class StoryRoles(TurnRoles):
    step = 0

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if schema is InteractionPlan:
            return InteractionPlan()
        if schema not in (ItemExtraction, SharedItemExtraction):
            return await super().structured(*args, **kwargs)
        self.calls.append((schema.__name__, args, kwargs))
        payload = json.loads(args[1])
        passages = list(payload["completed_narration"])
        if self.step == 0:
            return schema.model_validate(
                {
                    "actions": [item_action("LINA", "LINA", passages[0], "worn", ["pelvis"])],
                    "condition_updates": [
                        {
                            "operation": "record",
                            "target_id": ITEM["id"],
                            "kind": kind,
                            "part": "fabric",
                            "detail": detail,
                            "evidence": passages[index],
                        }
                        for kind, detail, index in [
                            ("fluid", "Water-soaked fabric.", 1),
                            ("contamination", "Blue ink.", 2),
                        ]
                    ],
                }
            )
        if self.step == 1:
            return schema.model_validate(
                {
                    "actions": [
                        item_action("LINA", "LINA", passages[0]),
                        item_action("LINA", PLAYER, passages[2]),
                    ],
                    "condition_updates": [
                        {
                            "operation": "record",
                            "target_id": ITEM["id"],
                            "kind": "other",
                            "part": "left seam",
                            "detail": "A small torn hole.",
                            "evidence": passages[1],
                        }
                    ],
                }
            )
        if self.step == 2:
            body = {"actions": [item_action(PLAYER, "MIKI", passages[0])]}
            if schema is SharedItemExtraction:
                body["staging"] = {
                    "props": [
                        {
                            "owner_id": "MIKI",
                            "item_action_index": 0,
                            "spatial_position": "inside the laundry basket on the table",
                            "status": "confirmed",
                            "visibility": "public",
                            "evidence": list(payload["completed_narration"].values())[1],
                        }
                    ]
                }
            return schema.model_validate(body)
        return schema.model_validate(
            {
                "actions": [item_action("MIKI", "MIKI", passages[2], "worn", ["pelvis"])],
                "condition_updates": [
                    {"operation": "clean", "condition_id": row["id"], "evidence": passages[0]}
                    for row in payload["physical_conditions"]["active"]
                    if row["kind"] in ("fluid", "contamination")
                ],
            }
        )


@pytest.mark.parametrize("staging", [False, True])
async def test_four_story_turns_keep_one_item_and_explicit_physical_consequences(
    monkeypatch, staging
):
    roles = StoryRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        npc.age_years = 30
        npc.inventory = [deepcopy(ITEM)]
        npc.visual_profile = {"appearance": {"age_years": 30}, "worn": [{"item_id": ITEM["id"]}]}
        db.add(
            WorldEntity(
                id="MIKI",
                session_id=state.session_id,
                name="Miki",
                entity_type="NPC",
                age_years=30,
                description="An adult archivist.",
                current_scene_id="START",
                inventory=[],
                visual_profile={"appearance": {"age_years": 30}, "worn": []},
                is_hidden=False,
            )
        )
        state.entity_states = {
            **state.entity_states,
            "__manifest_snapshot__": {
                "original_manifest": {"clothing_settings": {"detailed": True}}
            },
        }
        write_settings(state, VnSettings(scene_staging=staging))
        await db.commit()
        for step, text in enumerate(PASSAGES):
            roles.step = step
            monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", text)
            events = [
                event
                async for event in GameTurnManager(db, state.session_id, user).process_turn(
                    "Continue the laundry scene."
                )
            ]
            assert not any(event.startswith("event: error") for event in events), events
            await db.refresh(state)
            await db.refresh(avatar)
            rows = list(
                await db.scalars(
                    select(WorldEntity).where(WorldEntity.session_id == state.session_id)
                )
            )
            manager = SimpleNamespace(avatar=avatar, state=state)
            actors = actor_records(manager, rows)
            owner = [
                actor_id
                for actor_id, actor in actors.items()
                if any(item.get("id") == ITEM["id"] for item in actor["resolved_inventory"])
            ]
            expected_owner = ("LINA", PLAYER, "MIKI", "MIKI")[step]
            assert owner == [expected_owner]
            owned = next(
                item
                for item in actors[expected_owner]["resolved_inventory"]
                if item["id"] == ITEM["id"]
            )
            assert owned["description"] == ITEM["description"]
            worn = [
                entry
                for actor in actors.values()
                for entry in (actor.get("visual_profile") or {}).get("worn", [])
                if entry["item_id"] == ITEM["id"]
            ]
            assert bool(worn) is (step in (0, 3))
            if worn:
                assert worn[0]["uncovered_regions"] == ["pelvis"]
            conditions = list(read(state.entity_states).conditions.values())
            assert len(conditions) == (2 if step == 0 else 3)
            assert (
                all(row.status == "active" for row in conditions)
                if step < 3
                else all(row.status == "resolved" for row in conditions if row.kind != "other")
            )
            if step >= 1:
                assert next(row for row in conditions if row.kind == "other").status == "active"
            for condition in conditions:
                source = await db.get(ChatMessage, condition.latest.message_id)
                assert condition.latest.quote in source.content
            placed = props.project(state, props.candidates(avatar, rows, state, {"LINA", "MIKI"}))
            if staging and step == 2:
                assert any(
                    row["item_id"] == ITEM["id"] and "basket" in row["spatial_position"]
                    for row in placed
                )
            if step == 3:
                assert not any(row["item_id"] == ITEM["id"] for row in placed)
        assert (
            len(
                [
                    call
                    for call in roles.calls
                    if call[0] in ("ItemExtraction", "SharedItemExtraction")
                ]
            )
            == 4
        )
