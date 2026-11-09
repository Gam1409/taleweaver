"""Actual VN turns retain current scene facts outside the recent dialogue window."""

import json

from sqlalchemy import select

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.scene_continuity.ledger import read
from backend.engine.scene_illustrations.snapshots import registry_of
from backend.engine.scene_illustrations.visual_plan import inventory
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldScene
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn

TEXT = 'A fire burns in the fireplace. Lina points at the door. Lina: "Let us talk."'
ROOM = "Cobalt walls and a brass ceiling lamp. An old description of Lina's red dress."


class SceneRoles(TurnRoles):
    scene_updates = [
        {
            "operation": "record",
            "key": "fire",
            "kind": "process",
            "subject_id": "START",
            "detail": "Fire burns in the fireplace",
            "visual_detail": "A fire burns in the fireplace",
            "visibility": "public",
            "evidence": "A fire burns in the fireplace.",
        },
        {
            "operation": "record",
            "key": "interior",
            "kind": "environment",
            "subject_id": "START",
            "detail": "Cobalt walls and a brass ceiling lamp.",
            "visual_detail": "Cobalt walls and a brass ceiling lamp.",
            "visibility": "public",
            "source": "scene_description",
            "evidence": "Cobalt walls and a brass ceiling lamp.",
        },
    ]
    actions = [
        {
            "actor_ids": ["LINA"],
            "detail": "Lina points at the door.",
            "evidence": "Lina points at the door.",
        }
    ]

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if schema is ItemExtraction:
            self.calls.append((schema.__name__, args, kwargs))
            return ItemExtraction(
                scene_updates=self.scene_updates, final_frame_actions=self.actions
            )
        return await super().structured(*args, **kwargs)


async def test_saved_scene_state_survives_forty_dialogue_turns_and_freezes_source_time_image(
    monkeypatch,
):
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", TEXT)
    roles = SceneRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        scene = await db.scalar(select(WorldScene).where(WorldScene.id == "START"))
        scene.description = ROOM
        avatar.visual_profile = {"appearance": {"hair": "brown"}, "worn": []}
        state.max_memory_turns = 10
        await db.commit()
        events = [
            chunk
            async for chunk in GameTurnManager(db, state.session_id, user).process_turn(
                "Tell me more."
            )
        ]
        assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        ledger = read(state.entity_states)
        assert len(ledger.records) == 2 and not ledger.last_check["rejected"]
        process = next(row for row in ledger.records.values() if row.kind == "process")
        reply = await db.get(ChatMessage, process.origin.source_id)
        assert reply.content == TEXT and process.origin.quote in reply.content
        first_snapshot = registry_of(state.entity_states)["snapshots"][reply.id]
        assert "Cobalt walls" in str(first_snapshot["visible_facts"])
        assert "red dress" not in str(first_snapshot["visible_facts"])
        assert first_snapshot["visible_facts"]["visible_action"] == "Lina points at the door."
        action_atom = next(
            atom
            for atom in inventory(first_snapshot["visible_facts"])
            if atom.predicate == "visible_action"
        )
        assert action_atom.subject == "LINA" and action_atom.required
        assert len(roles.calls) == 3
        roles.scene_updates, roles.actions = [], []
        monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", 'Lina: "Continue."')
        for _ in range(40):
            events = [
                chunk
                async for chunk in GameTurnManager(db, state.session_id, user).process_turn(
                    "What else?"
                )
            ]
            assert final_payload(events)["status"] == "success", "".join(events)
        await db.refresh(state)
        assert read(state.entity_states).records[process.id] == process
        assert "Fire burns in the fireplace" in json.dumps(roles.prompts[-1], default=str)
        assert TEXT not in json.dumps(roles.prompts[-1], default=str)
        assert len(roles.calls) == 123  # Existing three calls per turn; no new summarizer.
        assert registry_of(state.entity_states)["snapshots"][reply.id] == first_snapshot
