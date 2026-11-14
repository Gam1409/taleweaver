"""One normal extraction handles a repeated scene fact and discloses bounded overflow."""

import json

from sqlalchemy import select

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.runtime import KEY
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import read as conditions
from backend.engine.scene_continuity.ledger import read as scene
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_vn_turn_integration import TurnRoles, final_payload, install_roles, seed_vn

PARTS = [
    "left_hand",
    "right_hand",
    "left_arm",
    "right_arm",
    "left_shoulder",
    "right_shoulder",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "forehead",
    "cheek",
    "chin",
]
FIRST = "The ceiling fan runs steadily."
LATER = "The ceiling fan now runs more quickly."
MARKS = [f"A blue paint mark is visible on Lina's {part.replace('_', ' ')}." for part in PARTS]


class DenseRoles(TurnRoles):
    dense = False
    extractions = 0

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if not issubclass(schema, ItemExtraction):
            return await super().structured(*args, **kwargs)
        self.calls.append((schema.__name__, args, kwargs))
        self.extractions += 1
        payload = json.loads(args[1])
        assert payload["extraction_limits"]["condition_updates"] == 12
        refs = list(payload["completed_narration"])
        updates = []
        tags = {"c0": ["scene"]}
        if self.dense:
            updates = [
                {
                    "operation": "record",
                    "target_id": "LINA",
                    "kind": "contamination",
                    "part": part,
                    "detail": MARKS[n],
                    "visibility": "public",
                    "evidence": refs[n + 1],
                }
                for n, part in enumerate(PARTS[:12])
            ]
            tags.update({f"c{n + 1}": ["conditions"] for n in range(12)})
            tags["c13"] = ["conditions_deferred"]
            known = payload["scene_continuity"]["saved"]["facts"]
            assert len(known) == 1 and known[0]["key"] == "ceiling_fan"
        return extraction(
            schema,
            coverage=tags,
            condition_updates=updates,
            scene_updates=[
                {
                    "operation": "record",
                    "key": "ceiling_fan",
                    "subject_id": "START",
                    "kind": "process",
                    "detail": LATER if self.dense else FIRST,
                    "visibility": "public",
                    "evidence": refs[0],
                }
            ],
        )


async def test_real_turn_preserves_identity_and_valid_facts_with_no_extra_extraction(monkeypatch):
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", FIRST)
    roles = DenseRoles()
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, _avatar, state, _ = await seed_vn(db)
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "Look at the ceiling."
            )
        ]
        assert final_payload(events)["status"] == "success"
        await db.refresh(state)
        original = next(iter(scene(state.entity_states).records.values()))
        assert len(roles.calls) == 3
        roles.dense = True
        monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", "\n".join([LATER, *MARKS]))
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "Continue observing."
            )
        ]
        assert final_payload(events)["status"] == "success"
        await db.refresh(state)
        facts = scene(state.entity_states)
        assert len(facts.records) == 1 and not facts.last_check["rejected"]
        assert facts.records[original.id].detail == LATER
        assert facts.records[original.id].origin == original.origin
        physical = conditions(state.entity_states)
        assert len(physical.conditions) == 12 and len(physical.last_check["accepted"]) == 12
        assert not physical.last_check["rejected"]
        assert PARTS[-1] not in {row.part for row in physical.conditions.values()}
        assert state.entity_states[KEY]["extraction_coverage"]["condition_budget"][
            "deferred_groups"
        ] == ["c13"]
        notices = list(
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == state.session_id, ChatMessage.role == "system"
                )
            )
        )
        assert any("budget" in row.content for row in notices)
        assert len(roles.calls) == 6
        assert roles.extractions == 2
