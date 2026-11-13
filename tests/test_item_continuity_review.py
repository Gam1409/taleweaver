"""Fresh current garment observations can replace unavailable placement evidence."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest
from sqlalchemy import select

from backend.engine.gameplay.manager import GameTurnManager
from backend.engine.narrated_items.apply import apply_actions
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.visual_novel.continuity import PLAYER
from backend.engine.visual_novel.schema import InteractionPlan
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_narrated_items import action, fixtures
from tests.test_vn_turn_integration import TurnRoles, install_roles, seed_vn

OLD_TEXT = "Lina raises her blue shirt above her waist."
CURRENT_TEXT = "Lina's blue shirt remains raised above her waist."


@pytest.mark.parametrize("source_message_id", [None, "unavailable-source"])
def test_current_wear_observation_replaces_unverified_displacement_proof(source_message_id):
    actors, snapshot = fixtures()
    old_text = "Anna raises her blue shirt above her waist."
    actors["NPC"]["visual_profile"]["worn"][0].update(
        uncovered_regions=["torso"],
        source={
            "source_message_id": source_message_id,
            "content_hash": sha256(old_text.encode()).hexdigest(),
            "evidence": old_text,
        },
    )
    current_text = "Anna's blue shirt remains raised above her waist."
    proposal = action(
        source_owner="NPC",
        destination_owner="NPC",
        disposition="worn",
        basis="observed_wear",
        uncovered_regions=["torso"],
        evidence=current_text,
    )

    changed, accepted, errors = apply_actions(
        ItemExtraction(actions=[proposal]),
        actors,
        snapshot,
        current_text,
        detailed=True,
        session_id="review-session",
        message_id="current-turn",
        verified_sources=set(),
    )

    assert not errors
    assert accepted, "A current exact observation must replace an unavailable old proof."
    worn = changed["NPC"]["visual_profile"]["worn"]
    assert len(worn) == 1
    assert worn[0]["item_id"] == "SHIRT"
    assert worn[0]["uncovered_regions"] == ["torso"]
    assert worn[0]["source"]["request_id"] == "current-turn"
    assert worn[0]["source"]["evidence"] == current_text
    assert worn[0]["source"]["content_hash"] == sha256(current_text.encode()).hexdigest()
    assert changed["NPC"]["inventory"] == actors["NPC"]["inventory"]
    assert changed[PLAYER] == actors[PLAYER]


class WearObservationRoles(TurnRoles):
    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if schema is InteractionPlan:
            self.calls.append((schema.__name__, args, kwargs))
            return InteractionPlan()
        if not issubclass(schema, ItemExtraction):
            return await super().structured(*args, **kwargs)
        self.calls.append((schema.__name__, args, kwargs))
        payload = json.loads(args[1])
        reference = next(iter(payload["completed_narration"]))
        return extraction(
            schema,
            actions=[
                action(
                    source_owner="LINA",
                    destination_owner="LINA",
                    disposition="worn",
                    basis="observed_wear",
                    uncovered_regions=["torso"],
                    evidence=reference,
                )
            ],
        )


async def seed_placement_source(db, state, user, kind):
    session_id = state.session_id
    if kind == "foreign":
        session_id = "other-review-session"
        db.add(
            GameSession(
                id=session_id,
                user_id=user.id,
                template_id=state.template_id,
                avatar_id=state.avatar_id,
            )
        )
        await db.flush()
    if kind == "missing":
        return
    db.add(
        ChatMessage(
            id="prior-wear-source",
            session_id=session_id,
            role="user" if kind in {"role", "valid_user"} else "assistant",
            content="Lina folds a map." if kind == "edited" else OLD_TEXT,
            is_debug=kind == "debug",
            scene_id="START",
        )
    )


@pytest.mark.parametrize(
    "kind", ["valid", "valid_user", "edited", "missing", "foreign", "role", "debug", "bad_span"]
)
async def test_saved_turn_refreshes_only_unverified_garment_proof(monkeypatch, kind):
    roles = WearObservationRoles()
    install_roles(monkeypatch, roles)
    monkeypatch.setattr("tests.test_vn_turn_integration.NARRATION", CURRENT_TEXT)
    async with TestSessionLocal() as db:
        user, avatar, state, _ = await seed_vn(db)
        session = await db.get(GameSession, state.session_id)
        session.content_language = "English"
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        shirt = deepcopy(fixtures()[1].items["SHIRT"])
        npc.name = "Lina"
        npc.age_years = 30
        npc.description = "An adult researcher."
        npc.inventory = [shirt]
        previous_source = {
            "request_id": None,
            "source_message_id": "prior-wear-source",
            "content_hash": sha256(OLD_TEXT.encode()).hexdigest(),
            "evidence": OLD_TEXT,
        }
        if kind == "valid_user":
            previous_source["source_role"] = "user"
        if kind == "bad_span":
            previous_source["evidence_span"] = {"start": 0, "end": 4}
        npc.visual_profile = {
            "appearance": {"age_years": 30},
            "worn": [
                {
                    "item_id": "SHIRT",
                    "uncovered_regions": ["torso"],
                    "source": previous_source,
                }
            ],
        }
        await seed_placement_source(db, state, user, kind)
        await db.commit()
        events = [
            event
            async for event in GameTurnManager(db, state.session_id, user).process_turn(
                "Continue the discussion."
            )
        ]
        assert not any(event.startswith("event: error") for event in events), events
        await db.refresh(state)
        await db.refresh(avatar)
        state_id = state.id
        expected_source = previous_source if kind in {"valid", "valid_user"} else None
        if expected_source is None:
            reply = await db.scalar(
                select(ChatMessage).where(
                    ChatMessage.session_id == state.session_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.content == CURRENT_TEXT,
                )
            )
            assert reply is not None
            expected_source = state.entity_states["LINA"]["visual_profile"]["worn"][0]["source"]
            assert expected_source["source_message_id"] == reply.id
            assert expected_source["evidence"] == CURRENT_TEXT
            assert expected_source["content_hash"] == sha256(CURRENT_TEXT.encode()).hexdigest()
        assert not any(item.get("id") == "SHIRT" for item in avatar.inventory)
    async with TestSessionLocal() as db:
        restored = await db.get(SessionState, state_id)
        override = restored.entity_states.get("LINA", {})
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        profile = override.get("visual_profile", npc.visual_profile)
        assert profile["worn"][0]["source"] == expected_source
        assert profile["worn"][0]["uncovered_regions"] == ["torso"]
        assert override.get("inventory", npc.inventory) == [shirt]
    assert (
        sum(name in {"ItemExtraction", "SharedItemExtraction"} for name, _, _ in roles.calls) == 1
    )
