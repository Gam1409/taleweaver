"""Isolated fixtures for explicitly invoked live contract checks; no response doubles."""

import hashlib
import json
import os

from sqlalchemy import delete, select

from backend.core.custom_openai import discover_models
from backend.core.security import encryption_util
from backend.engine.chpm.schema import KernelState, Settings
from backend.engine.chpm.state import KEY
from backend.engine.physical_conditions.ledger import apply
from backend.engine.turn_replay.snapshot import capture
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.npc_notebook import NpcNotebook
from backend.models.world_entity import WorldEntity, WorldExit, WorldScene
from scripts.live_checks.scenarios import CONTEXT, goal
from tests.test_vn_turn_integration import seed_vn

FOREIGN_NOTE = "FOREIGN_NOTE_7b9d42_DO_NOT_DISCLOSE"
COAT = {
    "id": "GREEN_COAT",
    "name": "Зелёное пальто",
    "description": "A green long-sleeved coat.",
    "clothing": {"layer": 2, "coverage": ["torso", "arms"], "opaque": True},
    "wearable_slots": ["Chest"],
}
NPC_COAT = {**COAT, "id": "BLUE_COAT", "name": "Синее пальто", "description": "A soaked blue coat."}


async def provider_settings(endpoint: str, model: str, tokens: int, timeout: int) -> dict:
    key = os.environ.get("TALEWEAVER_LIVE_API_KEY")
    if not model:
        available = await discover_models(endpoint, key)
        if len(available) != 1:
            raise ValueError("Specify --model when the endpoint advertises other than one model.")
        model = available[0]
    return {
        "custom_openai_url": endpoint,
        "custom_openai_response_format": "prompt",
        "custom_openai_timeout": timeout,
        "small_model_provider": "custom_openai",
        "complex_model_provider": "custom_openai",
        "small_model": model,
        "complex_model": model,
        "small_max_tokens": tokens,
        "complex_max_tokens": tokens,
    }


def profile(item_id: str) -> dict:
    return {"appearance": {"age_years": 32}, "worn": [{"item_id": item_id}]}


async def prepare(db, case, llm_settings: dict, tokens: int):
    user, avatar, state, _ = await seed_vn(db)
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == "session-1"))
    user.llm_settings = llm_settings
    key = os.environ.get("TALEWEAVER_LIVE_API_KEY")
    user.encrypted_api_keys = {"custom_openai": encryption_util.encrypt_key(key)} if key else {}
    user.tts_settings = {"enabled": False, "use_vocal_tags": False}
    avatar.inventory = [
        COAT,
        {"id": "SILVER_FLASK", "name": "Серебряная фляга", "description": "An empty silver flask."},
    ]
    avatar.visual_profile, avatar.equipment = profile("GREEN_COAT"), {"Chest": COAT}
    avatar.description = "An adult traveler in a green long-sleeved coat."
    game = await db.get(GameSession, "session-1")
    game.content_language = "Russian"
    scene = await db.scalar(
        select(WorldScene).where(WorldScene.session_id == game.id, WorldScene.id == "START")
    )
    scene.label, scene.description = "Диспетчерская", CONTEXT
    lina = await db.scalar(
        select(WorldEntity).where(WorldEntity.session_id == game.id, WorldEntity.id == "LINA")
    )
    lina.name, lina.age_years = "Лина", 32
    lina.character = (
        "A practical, curious adult who values honesty and makes her own contextual decisions."
    )
    lina.goal, lina.inventory = goal(case.scenario), [NPC_COAT]
    lina.visual_profile, lina.description = profile("BLUE_COAT"), "Lina, 32, wears a blue coat."
    state.quests = []
    state.entity_states = {
        "__vn_settings__": {"pace": "balanced"},
        KEY: KernelState(
            settings=Settings(
                mode=case.mode,
                actor_ids=["LINA"],
                workflow=case.workflow,
                tool_protocol=case.protocol,
                agent_steps=3,
                notebook_enabled=True,
                max_output_tokens=tokens,
                max_input_chars=64000,
                max_calls_per_turn=25,
                failure_policy="strict",
            )
        ).model_dump(mode="json"),
    }
    await add_room(db)
    if case.scenario == "condition_history":
        seed_conditions(db, state)
    await add_foreign_notebook(db, user.id)
    db.add(ChatMessage(session_id=game.id, role="assistant", content=CONTEXT, scene_id="START"))
    await db.commit()
    return user, state


async def add_room(db) -> None:
    db.add_all(
        [
            WorldScene(
                id="PORCH",
                session_id="session-1",
                label="Крытая веранда",
                description="A dry covered porch outside the unlocked dispatch-room door.",
            ),
            WorldExit(
                session_id="session-1",
                from_scene_id="START",
                to_scene_id="PORCH",
                label="На крытую веранду",
                is_locked=False,
            ),
            WorldExit(
                session_id="session-1",
                from_scene_id="PORCH",
                to_scene_id="START",
                label="В диспетчерскую",
                is_locked=False,
            ),
            WorldEntity(
                id="RADIO",
                session_id="session-1",
                entity_type="OBJECT",
                name="Рация",
                description="A recently restored radio on the table, repaired by Lina.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
            ),
            WorldEntity(
                id="LANTERN",
                session_id="session-1",
                entity_type="OBJECT",
                name="Фонарь",
                description="A lit portable lantern on the table.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
            ),
            WorldEntity(
                id="SPARE_COAT",
                session_id="session-1",
                entity_type="OBJECT",
                name="Сухое пальто",
                description="A dry spare coat on the table.",
                current_scene_id="START",
                is_hidden=False,
                is_in_inventory=False,
                metadata_json={"clothing": COAT["clothing"]},
                wearable_slots=["Chest"],
            ),
        ]
    )


def seed_conditions(db, state) -> None:
    text = "The traveler's right arm has an old shallow cut and is covered with fresh dirt."
    state.entity_states, accepted, rejected = apply(
        state.entity_states,
        [
            {
                "operation": "record",
                "target_id": "__player__",
                "kind": kind,
                "part": "right arm",
                "detail": detail,
                "evidence": text,
                "visibility": "public",
            }
            for kind, detail in (
                ("injury", "An old shallow cut."),
                ("contamination", "Fresh dirt."),
            )
        ],
        targets={"__player__"},
        narration=text,
        message_id="live-condition-source",
        session_id="session-1",
        minute=0,
    )
    if rejected or len(accepted) != 2:
        raise ValueError("Synthetic condition fixture failed validation.")
    db.add(
        ChatMessage(
            id="live-condition-source",
            session_id="session-1",
            role="assistant",
            content=text,
            scene_id="START",
        )
    )


async def add_foreign_notebook(db, user_id: str) -> None:
    payload = json.dumps({"private": FOREIGN_NOTE}, separators=(",", ":")).encode()
    db.add(
        NpcNotebook(
            user_id=user_id,
            session_id="session-1",
            npc_id="ABSENT",
            payload=payload,
            byte_size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            revision=1,
        )
    )


async def snapshot(db) -> dict:
    value = await capture(db, "session-1")
    notes = await db.scalars(select(NpcNotebook).where(NpcNotebook.session_id == "session-1"))
    value["notebooks"] = {
        note.npc_id: {"revision": note.revision, "data": json.loads(note.payload)} for note in notes
    }
    return value
