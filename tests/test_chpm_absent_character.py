"""Optional authored Character data must not break an accepted NPC selection."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.api.routes.adventures.gameplay_logic import GameTurnManager
from backend.engine.chpm import (
    appraisal_context,
    identity_adapter,
    inference,
    motivation,
    rendering,
)
from backend.engine.chpm.core.contracts import Genesis, Scope
from backend.engine.chpm.core.reducer import initial
from backend.engine.chpm.errors import RecoverableChpmError
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.schema import Settings
from backend.engine.chpm.state import load
from backend.models.game_session import GameSession
from backend.models.user import User
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_chpm_turn import ChpmRoles
from tests.test_vn_turn_integration import ACTION, install_roles, seed_vn


def authored(character=None, *, goal="Protect the bridge", profile=None):
    return SimpleNamespace(
        id="npc",
        character=character,
        goal=goal,
        metadata_json={"personality_profile": profile or {}},
    )


@pytest.mark.parametrize("character", [None, "", "   "])
@pytest.mark.parametrize("ground", ["goal", "profile"])
def test_absent_character_has_no_synthetic_identity_or_motive(character, ground):
    actor = authored(
        character,
        goal="Protect the bridge" if ground == "goal" else "",
        profile={"temperament": "calm"} if ground == "profile" else {},
    )
    identity = identity_adapter.from_actor(actor)
    assert identity.description == ""
    genesis = Genesis(
        scope=Scope(world_id="session", branch_id="main", observer_id="npc"), identity=identity
    )
    mind = Mind(genesis=genesis, snapshot=initial(genesis))
    catalogue = motivation.build(mind, [], appraisal_context.build(mind))
    assert "character" not in catalogue.sources
    assert {source.kind for source in catalogue.sources.values()} == {
        "authored_goal" if ground == "goal" else "authored_trait"
    }


def test_only_active_source_checked_personal_agenda_can_replace_absent_authored_grounds():
    from backend.engine.chpm.schema import AgendaClosure
    from tests.test_chpm_memory import entry
    from tests.test_chpm_motivation import declared

    identity = identity_adapter.from_actor(authored(goal=""))
    genesis = Genesis(
        scope=Scope(world_id="session", branch_id="main", observer_id="npc"), identity=identity
    )
    mind = Mind(genesis=genesis, snapshot=initial(genesis))
    active = declared()
    motivation.ensure_grounded(mind, [active])
    closed = active.model_copy(update={"closure": AgendaClosure(reason="withdraw", source=entry())})
    with pytest.raises(RecoverableChpmError, match="authored"):
        motivation.ensure_grounded(mind, [closed])
    with pytest.raises(RecoverableChpmError, match="authored"):
        motivation.ensure_grounded(mind, [])


class GroundedRoles(ChpmRoles):
    async def simple(self, system, payload, model, **kwargs):
        result = await super().simple(system, payload, model, **kwargs)
        if kwargs.get("phase") != "proposal":
            return result
        supplied = json.loads(payload)
        body = json.loads(result)
        source = supplied["motivation_context"]["sources"][0]["id"]
        for candidate in body["candidates"].values():
            candidate["motives"][0]["motive_id"] = source
            if not supplied["authored_goal"]:
                candidate.update(goal_alignment="unknown", goal_quote="")
        body["choice"]["motive_ids"] = [source]
        return json.dumps(body)


@pytest.mark.parametrize("character", [None, "", "   "])
@pytest.mark.parametrize("policy", ["continue", "strict"])
@pytest.mark.parametrize("ground", ["goal", "profile", "none"])
async def test_selectable_npc_with_absent_character_uses_existing_failure_policy(
    auth_client, monkeypatch, character, policy, ground
):
    roles = GroundedRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr(inference, "GameMasterLLM", roles)
    monkeypatch.setattr(rendering, "GameMasterLLM", roles)
    async with TestSessionLocal() as db:
        _, avatar, state, _ = await seed_vn(db)
        user = await db.scalar(select(User).where(User.username == "test_user"))
        game = await db.get(GameSession, "session-1")
        game.user_id = state.user_id = avatar.user_id = user.id
        npc = await db.scalar(
            select(WorldEntity).where(WorldEntity.session_id == game.id, WorldEntity.id == "LINA")
        )
        npc.character = character
        npc.goal = "Protect the bridge" if ground == "goal" else None
        npc.metadata_json = (
            {"personality_profile": {"temperament": "calm"}} if ground == "profile" else {}
        )
        await db.commit()
        response = await auth_client.patch(
            "/api/adventures/session-1/chpm",
            json={
                "settings": Settings(
                    mode="live", actor_ids=["LINA"], failure_policy=policy
                ).model_dump(),
                "expected_revision": 0,
            },
        )
        assert response.status_code == 200, response.text
        await db.refresh(state)
        for _ in range(2 if ground == "none" else 1):
            manager = GameTurnManager(db, "session-1", user)
            chunks = [chunk async for chunk in manager.process_turn(ACTION)]
            final = any(chunk.startswith("event: final") for chunk in chunks)
            assert final == (ground != "none" or policy == "continue"), "".join(chunks)
            saved = load(manager.state)
            if ground == "none":
                assert not saved.minds and not saved.actors
                assert "proposal" not in roles.chpm_calls
                if policy == "continue":
                    assert saved.usage.simplified
                    assert "authored" in saved.usage.detail.lower()
            else:
                assert saved.minds["LINA"].genesis.identity.description == ""
                assert roles.chpm_calls == ["perception", "proposal", "validation"]
