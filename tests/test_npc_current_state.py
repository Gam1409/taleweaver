"""Character cards project current visible facts without exposing private wardrobes."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.core.llm_router import GameMasterLLM
from backend.core.text_evidence import EvidenceSpan
from backend.engine.physical_conditions.ledger import apply, read
from backend.models.chat import ChatMessage
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]
URL = "/api/adventures/portrait-session/npcs/NPC_NEW"
TEXT = "A bandage covers her arm. A muddy stain marks the coat."


async def configure():
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        npc = await db.scalar(
            select(WorldEntity).where(
                WorldEntity.session_id == state.session_id, WorldEntity.id == "NPC_NEW"
            )
        )
        npc.visual_profile = {
            "appearance": {"age_years": 30},
            "worn": [
                {"item_id": "COAT", "uncovered_regions": ["torso"]},
                {"item_id": "SHIRT", "uncovered_regions": ["arms"]},
                {"item_id": "UNDERWEAR"},
            ],
        }
        npc.age_years = 30
        state.entity_states = {
            **state.entity_states,
            "__manifest_snapshot__": {
                "original_manifest": {"clothing_settings": {"detailed": True}}
            },
        }
        npc.inventory = ["COAT", "SHIRT", "UNDERWEAR"]
        npc.metadata_json = {"npc_journal": {"introduction": "Lina"}}
        for identifier, layer, regions in [
            ("COAT", 2, ["torso", "pelvis"]),
            ("SHIRT", 1, ["torso", "arms"]),
            ("UNDERWEAR", 0, ["pelvis"]),
        ]:
            db.add(
                WorldEntity(
                    id=identifier,
                    session_id=state.session_id,
                    entity_type="OBJECT",
                    name=identifier.title(),
                    description="A recorded garment.",
                    current_scene_id="TOWER",
                    image_url=f"/data/{identifier}.png",
                    metadata_json={
                        "clothing": {
                            "layer": layer,
                            "coverage": regions,
                            "underwear": identifier == "UNDERWEAR",
                        }
                    },
                )
            )
        changes = [
            ("NPC_NEW", "injury", "arm", "arms", "A bandage"),
            ("COAT", "contamination", "fabric", "pelvis", "A muddy stain"),
        ]
        states, accepted, errors = apply(
            state.entity_states,
            [
                {
                    "operation": "record",
                    "target_id": target,
                    "kind": kind,
                    "part": part,
                    "detail": "PRIVATE_MEDICAL_DETAIL",
                    "visibility": "public",
                    "visual_detail": visual,
                    "visual_region": region,
                    "evidence": TEXT,
                }
                for target, kind, part, region, visual in changes
            ],
            targets={"NPC_NEW", "COAT"},
            narration=TEXT,
            message_id="source",
            session_id=state.session_id,
            minute=480,
        )
        assert len(accepted) == 2 and not errors, errors
        state.entity_states = states
        await db.commit()
        return deepcopy(state.entity_states)


async def update_override(**values):
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {
            **state.entity_states,
            "NPC_NEW": {**state.entity_states["NPC_NEW"], **values},
        }
        await db.commit()


async def test_details_include_current_visible_clothing_and_conditions(
    auth_client, portrait_world, monkeypatch
):
    def no_model(*args, **kwargs):
        pytest.fail("Reading a character card must not call a model")

    monkeypatch.setattr(GameMasterLLM, "for_role", no_model)
    before = await configure()
    response = await auth_client.get(URL)
    assert response.status_code == 200, response.text
    current = response.json()["current_state"]
    assert current["availability"] == "present"
    assert current["game_minute"] == 480
    clothes = current["clothing"]["items"]
    assert [row["item_id"] for row in clothes] == ["COAT", "SHIRT"]
    assert clothes[0]["image_url"] == "/data/COAT.png"
    assert clothes[1]["uncovered_regions"] == ["arms"]
    assert {row["detail"] for row in current["conditions"]["items"]} == {
        "A bandage",
        "A muddy stain",
    }
    assert "UNDERWEAR" not in str(current) and "PRIVATE_MEDICAL_DETAIL" not in str(current)
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        assert state.entity_states == before
    assert portrait_world == []


@pytest.mark.parametrize("change", ["private", "resolved", "unavailable", "covered"])
async def test_conditions_follow_visibility_resolution_and_evidence(
    auth_client, portrait_world, change
):
    await configure()
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        ledger = read(state.entity_states)
        injury = next(row for row in ledger.conditions.values() if row.kind == "injury")
        if change == "private":
            injury.visibility = "private"
        elif change == "resolved":
            injury.status = "resolved"
        elif change == "unavailable":
            injury.latest.kind = "unavailable"
        else:
            override = {
                "metadata_json": {"clothing": {"layer": 2, "coverage": ["torso", "pelvis", "arms"]}}
            }
            state.entity_states = {**state.entity_states, "COAT": override}
        state.entity_states = {
            **state.entity_states,
            "__physical_conditions__": ledger.model_dump(),
        }
        await db.commit()
    current = (await auth_client.get(URL)).json()["current_state"]
    assert "A bandage" not in str(current)
    assert "A muddy stain" in str(current)


async def test_card_has_no_image_prompt_limit_and_uses_current_item_image(
    auth_client, portrait_world
):
    await configure()
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        ledger = read(state.entity_states)
        injury = next(row for row in ledger.conditions.values() if row.kind == "injury")
        ledger.conditions = {
            f"visible-{n}": injury.model_copy(update={"id": f"visible-{n}", "part": f"arm {n}"})
            for n in range(13)
        }
        state.entity_states = {
            **state.entity_states,
            "__physical_conditions__": ledger.model_dump(),
            "COAT": {"image_url": "/data/new-coat.png"},
        }
        db.add(
            WorldEntity(
                id="COAT",
                session_id="other-session",
                entity_type="OBJECT",
                name="SECRET_OTHER_SESSION",
                description="Other session only.",
                current_scene_id="OTHER",
                image_url="/data/other.png",
            )
        )
        await db.commit()
    current = (await auth_client.get(URL)).json()["current_state"]
    assert len(current["conditions"]["items"]) == 13
    assert current["clothing"]["items"][0]["image_url"] == "/data/new-coat.png"
    assert "SECRET_OTHER_SESSION" not in str(current)


@pytest.mark.parametrize(
    "override",
    [
        {"current_scene_id": "OTHER"},
        {"presence": "absent"},
        {"presence": "audible"},
        {"is_hidden": True},
    ],
)
async def test_known_off_scene_or_hidden_characters_do_not_expose_live_state(
    auth_client, portrait_world, override
):
    await configure()
    await update_override(**override)
    data = (await auth_client.get(URL)).json()["current_state"]
    assert data["availability"] == "not_present"
    assert not data["clothing"]["items"] and not data["conditions"]["items"]


async def test_inventory_override_clears_removed_garments_and_traces(auth_client, portrait_world):
    await configure()
    await update_override(inventory=["SHIRT"])
    data = (await auth_client.get(URL)).json()["current_state"]
    assert [row["item_id"] for row in data["clothing"]["items"]] == ["SHIRT"]
    assert "A muddy stain" not in str(data)


async def test_unknown_coverage_and_invalid_ledger_are_not_a_healthy_or_undressed_claim(
    auth_client, portrait_world
):
    await configure()
    await update_override(visual_profile={"version": 999})
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        state.entity_states = {**state.entity_states, "__physical_conditions__": {"version": 999}}
        await db.commit()
    data = (await auth_client.get(URL)).json()["current_state"]
    assert data["clothing"]["status"] == "unavailable"
    assert data["conditions"]["status"] == "unavailable"
    assert not data["clothing"]["items"] and not data["conditions"]["items"]


@pytest.mark.parametrize(
    "source_case", ["confirmed", "edited", "missing", "other_session", "private", "bad_span"]
)
async def test_known_pain_requires_its_public_original_source(
    auth_client, portrait_world, source_case
):
    await configure()
    text = 'Lina says, "My left leg hurts."'
    async with TestSessionLocal() as db:
        state = await db.scalar(
            select(SessionState).where(SessionState.session_id == "portrait-session")
        )
        states, accepted, errors = apply(
            state.entity_states,
            [
                {
                    "operation": "record",
                    "target_id": "NPC_NEW",
                    "kind": "pain",
                    "part": "left leg",
                    "detail": "PRIVATE_MEDICAL_DETAIL",
                    "visibility": "private" if source_case == "private" else "public",
                    "evidence": text,
                }
            ],
            targets={"NPC_NEW"},
            narration=text,
            message_id="pain-source",
            session_id=state.session_id,
            minute=485,
        )
        assert accepted and not errors, errors
        if source_case == "bad_span":
            ledger = read(states)
            ledger.conditions[accepted[0]].latest.evidence_span = EvidenceSpan(start=0, end=4)
            states["__physical_conditions__"] = ledger.model_dump()
        state.entity_states = states
        if source_case != "missing":
            db.add(
                ChatMessage(
                    id="pain-source",
                    session_id="other-session"
                    if source_case == "other_session"
                    else state.session_id,
                    role="assistant",
                    content="The original text was edited." if source_case == "edited" else text,
                )
            )
        await db.commit()
    current = (await auth_client.get(URL)).json()["current_state"]
    pain = [row for row in current["conditions"]["items"] if row["kind"] == "pain"]
    assert bool(pain) is (source_case == "confirmed")
    if pain:
        assert pain[0]["observation"] == "recorded" and pain[0]["detail"] == text
    assert "PRIVATE_MEDICAL_DETAIL" not in str(current)
