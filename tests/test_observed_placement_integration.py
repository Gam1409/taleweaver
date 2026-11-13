"""Current item observations persist through real turns, cards and source lifecycles."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.api.routes.adventures import regeneration
from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.core.config import settings
from backend.engine.clothing.body_schema import BodySlot
from backend.engine.narrated_items.runtime import KEY
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.physical_conditions.ledger import read
from backend.engine.visual_novel.schema import InteractionPlan
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.user import User
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_vn_turn_integration import TurnRoles, install_roles

pytestmark = pytest.mark.asyncio
SESSION = "observed-placement-session"
SLOT = get_args(BodySlot)[0]
TEXT = "Mira stands by the console, the empty sealed sensor resting in its configured body slot."
REWRITE = "Mira waits beside the quiet console."
SENSOR = {
    "id": "SENSOR",
    "name": "Sealed sensor",
    "description": "A small sealed instrument with a glass face.",
    "item_type": "DEFAULT",
    "calibration": {"serial": "synthetic-unit", "checked": True},
    "condition_links": [{"id": "retained-condition"}],
}


class ObservationRoles(TurnRoles):
    def __init__(self, *, destination="NPC_A", invalid_condition=False):
        super().__init__()
        self.destination = destination
        self.source_owner = "NPC_B"
        self.text = TEXT if destination == "NPC_A" else TEXT.replace("Mira", "Owen", 1)
        self.invalid_condition = invalid_condition
        self.extractions = 0
        self.rewrites = AsyncMock(return_value=REWRITE)

    def for_role(self, user, role, **kwargs):
        result = super().for_role(user, role, **kwargs)
        result.aexecute_simple_task = self.rewrites
        return result

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if issubclass(schema, ItemExtraction):
            self.extractions += 1
            condition = {
                "operation": "record",
                "target_id": "SENSOR",
                "kind": "item_state",
                "part": "contents",
                "detail": "filled",
                "evidence": self.text,
            }
            return extraction(
                schema,
                actions=[
                    {
                        "item_id": "SENSOR",
                        "source_owner": self.source_owner,
                        "destination_owner": self.destination,
                        "disposition": "worn",
                        "attachment_slot": SLOT,
                        "uncovered_regions": None,
                        "basis": "observed_placement",
                        "evidence": self.text,
                    }
                ],
                condition_updates=[condition] if self.invalid_condition else [],
                coverage={"c0": ["items", "conditions"] if self.invalid_condition else ["items"]},
            )
        if schema is InteractionPlan:
            return InteractionPlan()
        return await super().structured(*args, **kwargs)


@pytest_asyncio.fixture
async def observed_world(auth_client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == "test_user"))
        user.default_language = "English"
        user.earned_awards = []
        user.tts_settings = {"use_vocal_tags": False}
        adventure = AdventureTemplate(
            id="observed-placement-template",
            title="The Instrument Room",
            owner_id=user.id,
            rule_enforcement_mode="vn",
            is_ready=True,
            original_manifest={},
        )
        avatar = Avatar(
            id="observed-placement-avatar",
            user_id=user.id,
            name="Hero",
            role="Traveler",
            hp=100,
            exp=7,
            inventory=[],
            equipment={},
        )
        db.add_all([adventure, avatar])
        await db.flush()
        db.add(
            GameSession(
                id=SESSION,
                template_id=adventure.id,
                avatar_id=avatar.id,
                user_id=user.id,
                adventure_title=adventure.title,
                content_language="English",
                status="active",
            )
        )
        await db.flush()
        db.add(
            SessionState(
                session_id=SESSION,
                template_id=adventure.id,
                avatar_id=avatar.id,
                user_id=user.id,
                current_scene_id="START",
                entity_states={},
                enable_history_compression=False,
            )
        )
        db.add(
            WorldScene(
                id="START", session_id=SESSION, label="Instrument room", description="A quiet room."
            )
        )
        for identifier, name, inventory in [
            ("NPC_A", "Mira", []),
            ("NPC_B", "Owen", [deepcopy(SENSOR)]),
        ]:
            db.add(
                WorldEntity(
                    id=identifier,
                    session_id=SESSION,
                    entity_type="NPC",
                    name=name,
                    description="An adult technician.",
                    current_scene_id="START",
                    age_years=30,
                    is_hidden=False,
                    inventory=inventory,
                    character="Values careful observation.",
                    visual_profile={
                        "appearance": {"age_years": 30},
                        "worn": [],
                        "body": {"form": "humanoid", "attachment_slots": [SLOT]},
                    },
                )
            )
        db.add(
            WorldEntity(
                id="SENSOR",
                session_id=SESSION,
                entity_type="OBJECT",
                name=SENSOR["name"],
                description=SENSOR["description"],
                item_type="DEFAULT",
                current_scene_id="START",
                is_in_inventory=True,
                metadata_json=deepcopy(SENSOR),
            )
        )
        await db.commit()
        return user.id


async def play(monkeypatch, roles, user_id):
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", roles.text)
    install_roles(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user = await db.get(User, user_id)
        manager = GameTurnManager(db, SESSION, user)
        chunks = [chunk async for chunk in manager.process_turn("Observe the technicians.")]
        assert not any(chunk.startswith("event: error") for chunk in chunks), "".join(chunks)
        assert sum(chunk.startswith("event: final") for chunk in chunks) == 1
        reply = await db.scalar(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == SESSION,
                ChatMessage.role == "assistant",
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        )
        assert reply.content == roles.text
        return reply.id


async def card(client, session_id=SESSION, actor="NPC_A"):
    response = await client.get(f"/api/adventures/{session_id}/npcs/{actor}")
    assert response.status_code == 200, response.text
    return response.json()["current_state"]["clothing"]["items"]


async def stored(session_id=SESSION):
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == session_id))
        return deepcopy(state.entity_states)


@pytest.mark.parametrize("invalid_condition", [False, True])
async def test_observation_transfers_one_item_and_renders_saved_source(
    auth_client,
    observed_world,
    monkeypatch,
    invalid_condition,
):
    roles = ObservationRoles(invalid_condition=invalid_condition)
    source_id = await play(monkeypatch, roles, observed_world)
    states = await stored()
    assert states["NPC_B"]["inventory"] == []
    assert states["NPC_A"]["inventory"] == [SENSOR]
    assert states[KEY]["rejected"] == []
    assert len(states[KEY]["accepted"]) == 1 and roles.extractions == 1
    placement = states["NPC_A"]["visual_profile"]["worn"][0]
    assert placement["item_id"] == "SENSOR" and placement["attachment_slot"] == SLOT
    assert placement["source"]["source_message_id"] == source_id
    assert placement["source"]["content_hash"] == sha256(TEXT.encode()).hexdigest()
    assert placement["source"]["evidence"] == TEXT
    assert placement["source"]["evidence_span"] == {"start": 0, "end": len(TEXT)}
    occupied = await card(auth_client)
    assert [row["item_id"] for row in occupied] == ["SENSOR"]
    assert occupied[0]["slots"] == ["Body" + SLOT.title()]
    assert occupied[0]["uncovered_regions"] == []
    assert await card(auth_client, actor="NPC_B") == []
    conditions = read(states)
    assert not conditions.conditions
    assert bool(conditions.last_check["rejected"]) is invalid_condition
    async with TestSessionLocal() as db:
        objects = list(
            await db.scalars(
                select(WorldEntity).where(
                    WorldEntity.session_id == SESSION,
                    WorldEntity.entity_type == "OBJECT",
                )
            )
        )
        avatar = await db.get(Avatar, "observed-placement-avatar")
        user = await db.get(User, observed_world)
        assert [row.id for row in objects] == ["SENSOR"]
        assert (avatar.hp, avatar.exp, avatar.inventory, avatar.equipment, user.earned_awards) == (
            100,
            7,
            [],
            {},
            [],
        )


@pytest.mark.parametrize("operation", ["copy", "ads"])
async def test_observed_placement_sources_remap_and_rewrite_without_cross_session_leak(
    auth_client,
    observed_world,
    monkeypatch,
    operation,
):
    roles = ObservationRoles()
    source_id = await play(monkeypatch, roles, observed_world)
    assert [row["item_id"] for row in await card(auth_client)] == ["SENSOR"]
    if operation == "copy":
        response = await auth_client.post(f"/api/adventures/sessions/{SESSION}/copy")
        assert response.status_code == 201, response.text
    else:
        exported = await auth_client.get(f"/api/adventures/sessions/{SESSION}/export")
        assert exported.status_code == 200, exported.text
        response = await auth_client.post(
            "/api/adventures/sessions/import",
            files={
                "file": ("instrument-room.ads", exported.content, "application/zip"),
            },
        )
        assert response.status_code == 200, response.text
    destination = response.json()["game_id"]
    copied = await stored(destination)
    proof = copied["NPC_A"]["visual_profile"]["worn"][0]["source"]
    assert proof["source_message_id"] != source_id
    assert [item["id"] for item in copied["NPC_A"]["inventory"]] == ["SENSOR"]
    assert copied["NPC_B"]["inventory"] == []
    assert [row["item_id"] for row in await card(auth_client, destination)] == ["SENSOR"]
    async with TestSessionLocal() as db:
        source = await db.get(ChatMessage, proof["source_message_id"])
        request = await db.get(ChatMessage, proof["request_id"])
        assert (source.session_id, source.role, source.content) == (destination, "assistant", TEXT)
        assert (request.session_id, request.role) == (destination, "user")
    llm = SimpleNamespace(model="synthetic", aexecute_simple_task=roles.rewrites)
    monkeypatch.setattr(regeneration.GameMasterLLM, "for_role", lambda *_: llm)
    monkeypatch.setattr(regeneration, "schedule", MagicMock())
    monkeypatch.setattr(regeneration, "queue_refresh", MagicMock())
    rewritten = await auth_client.post(
        f"/api/adventures/{destination}/chat/regenerate",
        json={
            "message_id": proof["source_message_id"],
        },
    )
    assert rewritten.status_code == 200, rewritten.text
    assert await card(auth_client, destination) == []
    assert [row["item_id"] for row in await card(auth_client)] == ["SENSOR"]
    roles.rewrites.assert_awaited_once()


@pytest.mark.parametrize("destination,allowed", [("NPC_A", False), ("NPC_B", True)])
async def test_known_consumable_keeps_narrow_cross_owner_policy(
    auth_client,
    observed_world,
    monkeypatch,
    destination,
    allowed,
):
    async with TestSessionLocal() as db:
        carrier = await db.scalar(select(WorldEntity).where(WorldEntity.id == "NPC_B"))
        carrier.inventory = [{**deepcopy(SENSOR), "item_type": "CONSUMABLE"}]
        await db.commit()
    await play(monkeypatch, ObservationRoles(destination=destination), observed_world)
    states = await stored()
    assert bool(states[KEY]["accepted"]) is allowed
    assert bool(states[KEY]["rejected"]) is not allowed
    assert [row["item_id"] for row in await card(auth_client, actor=destination)] == (
        ["SENSOR"] if allowed else []
    )
    assert [
        item["id"] for item in states.get("NPC_B", {}).get("inventory", [{"id": "SENSOR"}])
    ] == ["SENSOR"]


async def test_repeated_observation_repairs_edited_proof_without_duplicating_ownership(
    auth_client,
    observed_world,
    monkeypatch,
):
    roles = ObservationRoles()
    await play(monkeypatch, roles, observed_world)
    roles.source_owner = "NPC_A"
    await play(monkeypatch, roles, observed_world)
    before = await stored()
    worn = before["NPC_A"]["visual_profile"]["worn"]
    assert len(worn) == 1 and before["NPC_A"]["inventory"] == [SENSOR]
    assert before["NPC_B"]["inventory"] == []
    assert [row["item_id"] for row in await card(auth_client)] == ["SENSOR"]
    async with TestSessionLocal() as db:
        source = await db.get(ChatMessage, worn[0]["source"]["source_message_id"])
        source.content = "A rewritten description of the console."
        await db.commit()
    assert await card(auth_client) == []
    fresh_id = await play(monkeypatch, roles, observed_world)
    restored = await stored()
    fresh_worn = restored["NPC_A"]["visual_profile"]["worn"]
    assert len(fresh_worn) == 1
    assert fresh_worn[0]["source"]["source_message_id"] == fresh_id
    assert restored["NPC_A"]["inventory"] == [SENSOR]
    assert restored["NPC_B"]["inventory"] == []
    assert [row["item_id"] for row in await card(auth_client)] == ["SENSOR"]
    assert roles.extractions == 3
