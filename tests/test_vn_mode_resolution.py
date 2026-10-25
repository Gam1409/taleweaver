"""Editor mode changes must agree across the runtime sheet, privacy and VN APIs."""

from unittest.mock import AsyncMock

from sqlalchemy import select

from backend.api.routes.adventures import gameplay
from backend.api.routes.adventures.logic import AdventureLogic
from backend.api.routes.adventures.unlock_service import award_session_unlock_xp
from backend.engine.visual_novel.presentation import session_is_vn, session_mode
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_scene_illustrations import illustration_world

__all__ = ["illustration_world"]


async def test_live_template_mode_edits_change_all_vn_surfaces(
    auth_client, illustration_world, monkeypatch
):
    monkeypatch.setattr(gameplay, "resolve_prompt_suggestions", AsyncMock(return_value=[]))
    monkeypatch.setattr(gameplay, "schedule_npc_journal", lambda *_: None)
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        # Leave a deliberately stale RPG snapshot, as existing saves do after editor changes.
        state.entity_states = {
            **state.entity_states,
            AdventureLogic.SESSION_MANIFEST_SNAPSHOT_KEY: {
                "adventure": {"rule_enforcement_mode": "rpg"}
            },
        }
        npc = await db.scalar(
            select(WorldEntity).where(WorldEntity.session_id == "moment", WorldEntity.id == "LINA")
        )
        npc.current_scene_id = "CAFE"
        npc.goal = "PRIVATE authored goal"
        await db.commit()

    for mode in ("rpg", "vn", "rpg"):
        edited = await auth_client.patch(
            "/api/adventures/moment-template", json={"rule_enforcement_mode": mode}
        )
        assert edited.status_code == 200, edited.text
        settings = await auth_client.get("/api/adventures/moment/vn-settings")
        image = await auth_client.get(
            "/api/adventures/moment/illustrations", params={"message_id": "moment-reply"}
        )
        assert settings.status_code == (200 if mode == "vn" else 409), settings.text
        assert image.status_code == (200 if mode == "vn" else 400), image.text
        async with TestSessionLocal() as db:
            state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
            avatar = await db.get(Avatar, state.avatar_id)
            assert await session_mode(db, state) == mode
            sheet = await AdventureLogic.build_sheet_snapshot(avatar, state, db)
            assert sheet["rule_enforcement_mode"] == mode
            assert sheet["mode_capabilities"]["vn"] is (mode == "vn")
            entities = await AdventureLogic.build_session_entities(db, state)
            lina = next(entity for entity in entities if entity["id"] == "LINA")
            if mode == "vn":
                assert "goal" not in lina
                assert "metadata_json" not in lina
                assert await award_session_unlock_xp(db, state, avatar, {}) == 0
            else:
                assert await award_session_unlock_xp(db, state, avatar, {}) > 0


async def test_missing_template_uses_snapshot_without_changing_detached_saves(
    auth_client, illustration_world
):
    async with TestSessionLocal() as db:
        state = await db.scalar(select(SessionState).where(SessionState.session_id == "moment"))
        template = await db.get(AdventureTemplate, state.template_id)
        template.rule_enforcement_mode = "rpg"
        assert not await session_is_vn(db, state)
        state.template_id = None
        assert await session_is_vn(db, state)
        assert await session_mode(db, state) == "vn"
