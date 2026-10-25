"""Private VN state and its provenance survive saves and rewind with their story."""

import io
import json
import zipfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import select

from backend.api.routes.adventures.logic import AdventureLogic
from backend.core.config import settings
from backend.engine import adventure_updates
from backend.engine.scene_illustrations.snapshots import REGISTRY_KEY
from backend.engine.scripting.runner import ScriptRunner
from backend.engine.session_checkpoint_service import SessionCheckpointService
from backend.engine.visual_novel.config import SETTINGS_KEY, VnSettings, write_settings
from backend.engine.visual_novel.lifecycle import remap_social_state
from backend.engine.visual_novel.schema import (
    STATE_KEY,
    CharacterState,
    Relationship,
    SocialMemory,
    SocialState,
)
from backend.engine.visual_novel.state import save_state, social_event_id
from backend.models.adventure_template import AdventureTemplate
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldScene
from backend.utils.path_security import data_url_to_local_path, local_path_to_data_url
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world", "vn_world"]

SESSION = "portrait-session"
FIRST_MESSAGE = "vn-source-before-checkpoint"
PRIVATE_CORE = "PRIVATE CORE: protect the hidden royal identity"
PRIVATE_GOAL = "PRIVATE GOAL: leave the city before the trial"
PRIVATE_MEMORY = "PRIVATE MEMORY: the letter was concealed from the visitor"


def social_fixture() -> SocialState:
    return SocialState(
        turn=7,
        processed_message_ids=[FIRST_MESSAGE],
        characters={
            "NPC_NEW": CharacterState(
                core=PRIVATE_CORE,
                goals=[PRIVATE_GOAL],
                relationship=Relationship(trust=12, affinity=4, respect=7, tension=3),
                emotion="guarded",
                emotion_cause=PRIVATE_MEMORY,
                next_intention="clarify",
                pinned=True,
                meaningful_events=3,
                last_source_message_id=FIRST_MESSAGE,
                memories=[
                    SocialMemory(
                        event_id=social_event_id(FIRST_MESSAGE, "NPC_NEW", "cooperation"),
                        source_message_id=FIRST_MESSAGE,
                        kind="cooperation",
                        evidence=PRIVATE_MEMORY,
                    )
                ],
            )
        },
    )


@pytest_asyncio.fixture
async def vn_world(portrait_world):
    image_path = (
        Path(settings.DATA_DIR)
        / "adventures"
        / "sessions"
        / SESSION
        / "visuals"
        / "illustrations"
        / "moment.png"
    )
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), "blue").save(image_path)
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        template.rule_enforcement_mode = "vn"
        template.strict_rules = False
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION))
        save_state(state, social_fixture())
        write_settings(state, VnSettings(pace="leisurely"))
        state.entity_states = {
            **state.entity_states,
            AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY: AdventureLogic.build_session_manifest_snapshot(
                template
            ),
            REGISTRY_KEY: {
                "version": 1,
                "snapshots": {
                    FIRST_MESSAGE: {
                        "nonce": "original-nonce",
                        "narration": "Two cups",
                        "visible_facts": {"setting": "room"},
                    }
                },
                "images": {
                    FIRST_MESSAGE: {
                        "image_url": local_path_to_data_url(str(image_path)),
                        "content_hash": "moment-hash",
                    }
                },
            },
        }
        db.add(
            WorldScene(id="TOWER", session_id=SESSION, label="Башня", description="A quiet room")
        )
        db.add(
            ChatMessage(
                id=FIRST_MESSAGE,
                session_id=SESSION,
                role="assistant",
                content="Lina sets two cups on the table.",
                scene_id="TOWER",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )
        await db.commit()


def test_remap_preserves_private_state_but_rebinds_only_message_references():
    original = {
        STATE_KEY: social_fixture().model_dump(),
        SETTINGS_KEY: {"pace": "leisurely"},
        "NPC_NEW": {"description": f"A story mentioning {FIRST_MESSAGE}"},
    }
    before = deepcopy(original)
    result = remap_social_state(original, {FIRST_MESSAGE: "new-local-source"})
    social = SocialState.model_validate(result[STATE_KEY])
    npc = social.characters["NPC_NEW"]
    assert original == before
    assert social.processed_message_ids == ["new-local-source"]
    assert npc.last_source_message_id == "new-local-source"
    assert npc.memories[0].source_message_id == "new-local-source"
    assert npc.memories[0].event_id == social_event_id("new-local-source", "NPC_NEW", "cooperation")
    assert npc.core == PRIVATE_CORE and npc.goals == [PRIVATE_GOAL]
    assert npc.relationship.trust == 12 and npc.memories[0].evidence == PRIVATE_MEMORY
    assert result["NPC_NEW"] == original["NPC_NEW"]
    assert result[SETTINGS_KEY] == original[SETTINGS_KEY]


def test_remap_drops_orphaned_provenance_without_resetting_relationships():
    result = remap_social_state({STATE_KEY: social_fixture().model_dump()}, {})
    social = SocialState.model_validate(result[STATE_KEY])
    npc = social.characters["NPC_NEW"]
    assert not social.processed_message_ids and not npc.memories
    assert npc.last_source_message_id == ""
    assert npc.relationship.trust == 12 and npc.meaningful_events == 3
    assert npc.core == PRIVATE_CORE


@pytest.mark.parametrize("raw", [{"version": 99, "unknown": "preserve"}, "invalid"])
def test_remap_preserves_unsupported_state_for_future_compatible_reader(raw):
    original = {STATE_KEY: raw, "NPC_NEW": {"hp": 12}}
    assert remap_social_state(original, {}) == original


async def test_copy_and_export_import_preserve_private_state_with_local_provenance(
    auth_client, vn_world
):
    copied = await auth_client.post(f"/api/adventures/sessions/{SESSION}/copy")
    assert copied.status_code == 201, copied.text
    exported = await auth_client.get(f"/api/adventures/sessions/{SESSION}/export")
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("session.json"))
    exported_states = manifest["session_state"]["entity_states"]
    assert exported_states[STATE_KEY] == social_fixture().model_dump()
    assert exported_states[SETTINGS_KEY] == {"pace": "leisurely"}
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("novel.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    for sid in (copied.json()["game_id"], imported.json()["game_id"]):
        settings_response = await auth_client.get(f"/api/adventures/{sid}/vn-settings")
        assert settings_response.status_code == 200, settings_response.text
        assert settings_response.json() == {"mode": "vn", "settings": {"pace": "leisurely"}}
    async with TestSessionLocal() as db:
        original = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION))
        for sid in (copied.json()["game_id"], imported.json()["game_id"]):
            state = await db.scalar(select(SessionState).where(SessionState.session_id == sid))
            message = await db.scalar(select(ChatMessage).where(ChatMessage.session_id == sid))
            assert message.id != FIRST_MESSAGE
            expected = remap_social_state(original.entity_states, {FIRST_MESSAGE: message.id})
            assert state.entity_states[STATE_KEY] == expected[STATE_KEY]
            assert state.entity_states[SETTINGS_KEY] == {"pace": "leisurely"}
            registry = state.entity_states[REGISTRY_KEY]
            assert set(registry["images"]) == {message.id}
            assert set(registry["snapshots"]) == {message.id}
            assert registry["snapshots"][message.id]["nonce"] != "original-nonce"
            image_url = registry["images"][message.id]["image_url"]
            assert image_url.startswith(f"/data/adventures/sessions/{sid}/")
            image_path = Path(data_url_to_local_path(image_url))
            assert image_path.is_file()
            assert (
                image_path.read_bytes()
                == Path(
                    data_url_to_local_path(
                        original.entity_states[REGISTRY_KEY]["images"][FIRST_MESSAGE]["image_url"]
                    )
                ).read_bytes()
            )
            state.entity_states = {**state.entity_states, STATE_KEY: SocialState().model_dump()}
        await db.commit()
    async with TestSessionLocal() as db:
        original = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION))
        assert original.entity_states[STATE_KEY] == social_fixture().model_dump()


async def test_vn_export_remains_playable_when_original_template_is_unavailable(
    auth_client, vn_world
):
    exported = await auth_client.get(f"/api/adventures/sessions/{SESSION}/export")
    assert exported.status_code == 200
    deleted = await auth_client.delete("/api/adventures/portrait-template")
    assert deleted.status_code == 200, deleted.text
    imported = await auth_client.post(
        "/api/adventures/sessions/import",
        files={"file": ("novel.ads", exported.content, "application/zip")},
    )
    assert imported.status_code == 200, imported.text
    sid = imported.json()["game_id"]
    response = await auth_client.get(f"/api/adventures/{sid}/vn-settings")
    assert response.status_code == 200, response.text
    assert response.json() == {"mode": "vn", "settings": {"pace": "leisurely"}}
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == sid))
        assert state.template_id is None
        assert state.entity_states[STATE_KEY]["characters"]["NPC_NEW"]["core"] == PRIVATE_CORE


async def test_checkpoint_rewinds_feelings_goals_promotion_settings_and_future_provenance(vn_world):
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == SESSION))
        before = deepcopy(state.entity_states)
        checkpoint = await SessionCheckpointService.create_checkpoint(db, SESSION, "manual")
        await db.commit()
        future = social_fixture()
        future.characters["NPC_NEW"].relationship.trust = -40
        future.characters["NPC_NEW"].goals = ["A future secret plan"]
        future.characters["NPC_NEW"].pinned = False
        future.characters["NPC_NEW"].meaningful_events = 0
        future.processed_message_ids.append("vn-future-message")
        save_state(state, future)
        write_settings(state, VnSettings(pace="brisk"))
        changed = deepcopy(state.entity_states)
        changed[REGISTRY_KEY]["images"]["vn-future-message"] = {"image_url": "/data/future.png"}
        state.entity_states = changed
        db.add(
            ChatMessage(
                id="vn-future-message",
                session_id=SESSION,
                role="assistant",
                content="An argument that will be undone.",
                scene_id="TOWER",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=5),
            )
        )
        await db.commit()
        removed = await SessionCheckpointService.restore_checkpoint(db, SESSION, checkpoint.id)
        await db.commit()
        assert removed == 1
        assert state.entity_states == before
        assert await db.get(ChatMessage, "vn-future-message") is None
        assert await db.get(ChatMessage, FIRST_MESSAGE) is not None


@pytest.mark.parametrize("mode,should_run", [("vn", False), ("rpg", True)])
async def test_session_start_skips_stale_rpg_init_scripts_only_in_vn(
    auth_client, portrait_world, monkeypatch, mode, should_run
):
    monkeypatch.setattr(
        adventure_updates,
        "check_template_update",
        lambda *_: {"is_legacy_format": False, "can_start": True},
    )
    runner = Mock(wraps=ScriptRunner.run_init_script)

    def run_init(self, context):
        return runner(self, context)

    monkeypatch.setattr(ScriptRunner, "run_init_script", run_init)
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        template.rule_enforcement_mode = mode
        template.original_manifest = {
            "init_script": "tw.print('Old RPG initialization')",
            "scripts": [
                {"id": "OLD_INIT", "trigger": "on_init", "code": "tw.print('Old RPG event')"}
            ],
        }
        await db.commit()
    response = await auth_client.post("/api/adventures/portrait-template/sessions/start")
    assert response.status_code == 201, response.text
    assert runner.called is should_run
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == response.json()["game_id"])
        )
        assert ("__script_vars__" in state.entity_states) is should_run
