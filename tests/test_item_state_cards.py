"""Current item properties reach available public item views without private values."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.core.llm_router import GameMasterLLM
from backend.engine.physical_conditions.ledger import apply, read
from backend.engine.visual_novel.presentation import public_entity
from backend.models.adventure_template import AdventureTemplate
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity, WorldScene
from tests.conftest import TestSessionLocal
from tests.test_npc_current_state import URL, configure
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@pytest.mark.asyncio
async def test_npc_card_projects_current_value_and_public_equipment_properties(
    auth_client, portrait_world
):
    await configure()
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        report = "The coat is crumpled."
        narration = "You check the coat and confirm that."
        player = ChatMessage(
            id="item-report", session_id=state.session_id, role="user", content=report
        )
        reply = ChatMessage(
            id="item-confirmation", session_id=state.session_id, role="assistant", content=narration
        )
        db.add_all([player, reply])
        await db.flush()
        state.entity_states, accepted, errors = apply(
            state.entity_states,
            [
                dict(
                    operation="record",
                    target_id="COAT",
                    kind="item_state",
                    part="form",
                    detail=report,
                    evidence=narration,
                    player_evidence=report,
                    visibility="public",
                ),
                dict(
                    operation="record",
                    target_id="COAT",
                    kind="item_state",
                    part="inscription",
                    detail="A private inscription.",
                    evidence="A private inscription.",
                    visibility="private",
                ),
            ],
            targets={"COAT"},
            item_targets={"COAT"},
            narration=narration + " A private inscription.",
            message_id=reply.id,
            player_message=(player.id, report),
            session_id=state.session_id,
            minute=50,
        )
        # The reply text and evidence hash must agree, as in a completed real turn.
        reply.content += " A private inscription."
        assert not errors and len(accepted) == 2
        await db.commit()
    response = await auth_client.get(URL)
    assert response.status_code == 200, response.text
    data = response.json()["current_state"]
    coat = next(item for item in data["clothing"]["items"] if item["item_id"] == "COAT")
    assert coat["current_state"] == [dict(dimension="form", detail=report, last_changed_minute=50)]
    condition = next(item for item in data["conditions"]["items"] if item["kind"] == "item_state")
    assert condition["detail"] == report
    assert condition["kind"] == "item_state" and condition["part"] == "form"
    assert "A private inscription." not in str(data)


@pytest.mark.parametrize(
    "metadata,override,available",
    [
        ({"locked": True}, {}, False),
        ({"code_to_unlock": "ARCHIVE-CODE"}, {}, False),
        ({"item_to_unlock": "ARCHIVE-KEY"}, {}, False),
        ({"rule_to_unlock": "The archivist grants access."}, {}, False),
        ({}, {"locked": True}, False),
        ({"locked": True, "code_to_unlock": "ARCHIVE-CODE"}, {"locked": False}, True),
        ({}, {}, True),
    ],
)
@pytest.mark.asyncio
async def test_chat_only_enriches_available_container_contents(
    auth_client, portrait_world, monkeypatch, metadata, override, available
):
    async def no_suggestions(*_args, **_kwargs):
        return []

    def no_model(*_args, **_kwargs):
        pytest.fail("Reading current item properties must not call a model")

    monkeypatch.setattr(
        "backend.api.routes.adventures.gameplay.resolve_prompt_suggestions", no_suggestions
    )
    monkeypatch.setattr(GameMasterLLM, "for_role", no_model)
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        template = await db.get(AdventureTemplate, state.template_id)
        template.rule_enforcement_mode = "vn"
        db.add(
            WorldScene(
                id="TOWER",
                session_id=state.session_id,
                label="Archive tower",
                description="A quiet room.",
            )
        )
        db.add_all(
            [
                WorldEntity(
                    id="BOX",
                    session_id=state.session_id,
                    entity_type="OBJECT",
                    name="Archive box",
                    description="An archive box.",
                    item_type="CONTAINER",
                    current_scene_id="TOWER",
                    inventory=["FLASK"],
                    metadata_json=metadata,
                ),
                WorldEntity(
                    id="FLASK",
                    session_id=state.session_id,
                    entity_type="OBJECT",
                    name="Flask",
                    description="An originally full flask.",
                    item_type="PICKABLE",
                    current_scene_id="TOWER",
                ),
            ]
        )
        text = "The flask is empty. The flask has a private label. The box is wet."
        reply = ChatMessage(session_id=state.session_id, role="assistant", content=text)
        db.add(reply)
        await db.flush()
        facts = [
            ("FLASK", "fill_level", "The flask is empty.", "public"),
            ("FLASK", "inscription", "The flask has a private label.", "private"),
            ("BOX", "wetness", "The box is wet.", "public"),
        ]
        state.entity_states = {**state.entity_states, "BOX": override}
        state.entity_states, accepted, errors = apply(
            state.entity_states,
            [
                dict(
                    operation="record",
                    target_id=target,
                    kind="item_state",
                    part=part,
                    detail=detail,
                    evidence=detail,
                    visibility=visibility,
                )
                for target, part, detail, visibility in facts
            ],
            targets={"BOX", "FLASK"},
            item_targets={"BOX", "FLASK"},
            narration=text,
            message_id=reply.id,
            session_id=state.session_id,
            minute=480,
        )
        assert len(accepted) == 3 and not errors
        await db.commit()
    response = await auth_client.get("/api/adventures/portrait-session/chat?include_messages=false")
    assert response.status_code == 200, response.text
    entities = response.json()["entities"]
    assert all(row["id"] != "FLASK" for row in entities)
    box = next(row for row in entities if row["id"] == "BOX")
    assert box["current_state"][0]["detail"] == "The box is wet."
    child = box["inventory"][0]
    assert {key: child[key] for key in ("id", "name", "description")} == {
        "id": "FLASK",
        "name": "Flask",
        "description": "An originally full flask.",
    }
    assert ("current_state" in child) is available
    if available:
        assert child["current_state"] == [
            dict(dimension="fill_level", detail="The flask is empty.", last_changed_minute=480)
        ]
    assert "The flask has a private label." not in str(entities)
    async with TestSessionLocal() as db:
        stored_box = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == "portrait-session", WorldEntity.id == "BOX"
            )
        )
        stored_state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert stored_box.inventory == ["FLASK"]
        assert len(read(stored_state.entity_states).conditions) == 3


def test_unavailable_container_clears_copied_property_view_without_mutating_inventory():
    entity = {
        "id": "BOX",
        "entity_type": "OBJECT",
        "item_type": "CONTAINER",
        "locked": True,
        "inventory": [
            {"id": "FLASK", "name": "Flask", "current_state": [{"detail": "STALE_PROPERTY"}]},
            "LEGACY_REF",
        ],
    }
    before = deepcopy(entity)
    result = public_entity(entity, SimpleNamespace(entity_states={}))
    assert result["inventory"] == [{"id": "FLASK", "name": "Flask"}, "LEGACY_REF"]
    assert entity == before
