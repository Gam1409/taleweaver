"""Legacy inline imports retain facts while rebinding their owned source records."""

from copy import deepcopy
from hashlib import sha256
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from backend.engine.clothing.body_schema import WearCommandProof, WearSource
from backend.engine.clothing.profiles import load_profile
from backend.engine.clothing.wear_provenance import command_matches
from backend.engine.physical_conditions.command_source import CommandProof
from backend.engine.physical_conditions.item_commands import apply_command
from backend.engine.physical_conditions.ledger import apply, read
from backend.engine.physical_conditions.schema import KEY as CONDITIONS_KEY
from backend.engine.physical_conditions.visuals import retract
from backend.models.adventure_template import AdventureTemplate
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.game_session import GameSession
from backend.models.session_state import SessionState
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.test_legacy_session_bundle import bundle as legacy_bundle

bundle = legacy_bundle

INPUT_ID = "old-input"
REPLY_ID = "old-reply"
INPUT = "I wait by the bench."
REPLY = "The guide has a bruised wrist. The coats have open sleeves."
WEAR = "The coats have open sleeves."


def _digest(text: str) -> str:
    return sha256(text.encode()).hexdigest()


def _conditions() -> dict:
    states, _, errors = apply(
        {},
        [
            {
                "operation": "record",
                "target_id": "GUIDE",
                "kind": "injury",
                "part": "wrist",
                "detail": "A bruised wrist.",
                "visibility": "public",
                "visual_detail": "a bruised wrist",
                "visual_region": "arms",
                "evidence": "The guide has a bruised wrist.",
            }
        ],
        targets={"GUIDE"},
        narration=REPLY,
        message_id=REPLY_ID,
        session_id="old-session",
        minute=12,
    )
    assert not errors
    states, _ = apply_command(
        states,
        item_id="GUIDE_COAT",
        dimension="surface",
        detail="A damp surface.",
        owned_item_ids={"GUIDE_COAT"},
        proof=CommandProof(id="command_surface", actor_id="GUIDE", operation="change_item_state"),
        message_id=INPUT_ID,
        request_hash=_digest("surface command"),
        session_id="old-session",
        minute=13,
    )
    return states


def _profile(kind: str, actor: str, item: str, regions: list[str]) -> dict:
    source = WearSource(
        request_id=INPUT_ID,
        source_message_id=REPLY_ID,
        content_hash=_digest(REPLY),
        evidence=WEAR,
    )
    if kind == "command":
        source = WearSource.from_command(
            WearCommandProof(
                command_id="command_" + item,
                actor_id=actor,
                item_id=item,
                input_id=INPUT_ID,
                input_hash=_digest(INPUT),
                input_revision="input-revision",
                request_hash=_digest("adjust " + item),
                operation="adjust_clothing",
            )
        )
    return {
        "version": 1,
        "appearance": {"hair": "Brown hair", "age_years": 30},
        "worn": [{"item_id": item, "uncovered_regions": regions, "source": source.model_dump()}],
    }


def _sourced_bundle(payload: dict[str, Any], kind: str) -> dict[str, Any]:
    result = deepcopy(payload)
    result["chat_history"] = [
        {
            "id": INPUT_ID,
            "role": "user",
            "content": INPUT,
            "revision_id": "input-revision",
            "scene_id": "ROOM",
        },
        {
            "id": REPLY_ID,
            "role": "assistant",
            "content": REPLY,
            "revision_id": "reply-revision",
            "scene_id": "ROOM",
        },
    ]
    garment = {"layer": 2, "coverage": ["torso", "arms"]}
    result["avatar"].update(
        inventory=[{"id": "HERO_COAT", "name": "Hero coat", "clothing": garment}],
        visual_profile=_profile(kind, "__player__", "HERO_COAT", ["arms"]),
    )
    result["entities"][0].update(
        inventory=[{"id": "GUIDE_COAT", "name": "Guide coat", "clothing": garment}],
        visual_profile=_profile(kind, "GUIDE", "GUIDE_COAT", ["arms"]),
    )
    result["game_state"]["entity_states"] = {
        **_conditions(),
        "GUIDE": {
            "visual_profile": _profile(kind, "GUIDE", "GUIDE_COAT", ["torso"]),
            "unrelated": "Retained runtime state.",
        },
        "__future_state__": {"version": 99, "source_message_id": INPUT_ID},
    }
    return result


async def _import(
    client: AsyncClient, payload: dict[str, Any]
) -> tuple[Avatar, WorldEntity, SessionState, dict[str, ChatMessage]]:
    response = await client.post("/api/adventures/import/session-bundle", json=payload)
    assert response.status_code == 200, response.text
    async with TestSessionLocal() as db:
        game = await db.scalar(
            select(GameSession).where(GameSession.template_id == response.json()["adventure_id"])
        )
        assert game is not None
        avatar = await db.get(Avatar, game.avatar_id)
        guide = await db.scalar(select(WorldEntity).where(WorldEntity.session_id == game.id))
        state = await db.scalar(select(SessionState).where(SessionState.session_id == game.id))
        messages = await db.scalars(select(ChatMessage).where(ChatMessage.session_id == game.id))
        assert avatar is not None and guide is not None and state is not None
        return avatar, guide, state, {message.role: message for message in messages}


async def test_legacy_import_rebinds_physical_sources_and_later_visual_retraction(
    auth_client: AsyncClient, bundle: dict[str, Any]
) -> None:
    payload = _sourced_bundle(bundle, "narration")
    before = read(payload["game_state"]["entity_states"])
    _, _, state, messages = await _import(auth_client, payload)
    after = read(state.entity_states)
    assert after.revision == before.revision and after.conditions.keys() == before.conditions.keys()
    by_kind = {"narration": messages["assistant"], "command": messages["user"]}
    for key, condition in after.conditions.items():
        original = before.conditions[key]
        expected = by_kind[original.latest.kind]
        assert condition.origin.message_id == condition.latest.message_id == expected.id
        assert condition.latest.content_hash == original.latest.content_hash
        assert condition.latest.command == original.latest.command
        assert condition.model_dump(exclude={"origin", "latest"}) == original.model_dump(
            exclude={"origin", "latest"}
        )
    assert all(event.source.message_id == by_kind[event.source.kind].id for event in after.events)
    assert after.last_check["message_id"] == messages["user"].id
    assert any(row.visual_detail == "a bruised wrist" for row in after.conditions.values())
    retract(state, messages["assistant"].id)
    injury = next(
        row for row in read(state.entity_states).conditions.values() if row.kind == "injury"
    )
    assert injury.detail == "A bruised wrist." and injury.visual_detail == ""


@pytest.mark.parametrize("kind", ["narration", "command"])
async def test_legacy_import_rebinds_avatar_base_npc_and_override_wear_sources(
    auth_client: AsyncClient, bundle: dict[str, Any], kind: str
) -> None:
    payload = _sourced_bundle(bundle, kind)
    avatar, guide, state, messages = await _import(auth_client, payload)
    profiles = [
        (avatar.visual_profile, "__player__", "HERO_COAT", ["arms"]),
        (guide.visual_profile, "GUIDE", "GUIDE_COAT", ["arms"]),
        (state.entity_states["GUIDE"]["visual_profile"], "GUIDE", "GUIDE_COAT", ["torso"]),
    ]
    for raw, actor, item, regions in profiles:
        profile = load_profile(raw)
        assert profile is not None
        worn = profile.worn[0]
        assert worn.item_id == item and worn.uncovered_regions == regions
        source = worn.source
        assert source is not None and source.request_id == messages["user"].id
        expected = messages["user"] if kind == "command" else messages["assistant"]
        assert source.source_message_id == expected.id
        if kind == "command":
            assert command_matches(source, expected, actor_id=actor, item_id=item)
        else:
            assert source.content_hash == _digest(REPLY) and source.evidence == WEAR
    assert avatar.inventory == payload["avatar"]["inventory"]
    assert guide.inventory == payload["entities"][0]["inventory"]
    assert state.entity_states["GUIDE"]["unrelated"] == "Retained runtime state."
    assert (
        state.entity_states["__future_state__"]
        == payload["game_state"]["entity_states"]["__future_state__"]
    )


@pytest.mark.parametrize("kind", ["narration", "command"])
async def test_legacy_import_keeps_physical_and_wear_facts_when_sources_are_missing(
    auth_client: AsyncClient, bundle: dict[str, Any], kind: str
) -> None:
    payload = _sourced_bundle(bundle, kind)
    payload["chat_history"] = []
    avatar, guide, state, messages = await _import(auth_client, payload)
    assert not messages
    ledger = read(state.entity_states)
    for condition in ledger.conditions.values():
        assert condition.latest.kind == condition.origin.kind == "unavailable"
        assert condition.latest.message_id is None and condition.origin.message_id is None
        assert condition.detail in {"A bruised wrist.", "A damp surface."}
    assert all(event.source.kind == "unavailable" for event in ledger.events)
    for raw in [
        avatar.visual_profile,
        guide.visual_profile,
        state.entity_states["GUIDE"]["visual_profile"],
    ]:
        profile = load_profile(raw)
        assert profile is not None and profile.worn[0].source is not None
        source = profile.worn[0].source
        assert source.request_id is None and source.source_message_id is None
        if source.command is not None:
            assert source.command.input_id is None


async def test_legacy_import_preserves_unsupported_profiles_and_unrelated_state(
    auth_client: AsyncClient, bundle: dict[str, Any]
) -> None:
    payload = _sourced_bundle(bundle, "command")
    future = {"version": 99, "future_fields": {"source_message_id": INPUT_ID}}
    payload["avatar"]["visual_profile"] = deepcopy(future)
    payload["entities"][0]["visual_profile"] = deepcopy(future)
    payload["game_state"]["entity_states"]["GUIDE"]["visual_profile"] = deepcopy(future)
    avatar, guide, state, _ = await _import(auth_client, payload)
    assert avatar.visual_profile == guide.visual_profile == future
    assert state.entity_states["GUIDE"]["visual_profile"] == future
    assert (
        state.entity_states["__future_state__"]
        == payload["game_state"]["entity_states"]["__future_state__"]
    )


async def test_legacy_import_rejects_unsupported_physical_ledger_without_partial_state(
    auth_client: AsyncClient, bundle: dict[str, Any]
) -> None:
    payload = _sourced_bundle(bundle, "command")
    payload["game_state"]["entity_states"][CONDITIONS_KEY]["version"] = 99
    response = await auth_client.post("/api/adventures/import/session-bundle", json=payload)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Session bundle import failed."
    async with TestSessionLocal() as db:
        columns = [
            AdventureTemplate.id,
            GameSession.id,
            Avatar.id,
            ChatMessage.id,
            SessionState.session_id,
            WorldEntity.pk,
        ]
        for column in columns:
            assert await db.scalar(select(func.count(column))) == 0
