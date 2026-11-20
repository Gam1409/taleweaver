"""Exercise the public route with SQLite snapshots, real alignment and a local model stub."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.api.routes.adventures import prose_evidence as route
from backend.core.auth import create_user_access_token
from backend.engine.turn_replay.snapshot import capture
from backend.engine.visual_novel.concurrency import session_write_lease
from backend.models.chat import ChatMessage
from backend.models.turn_replay import TurnReplay
from tests.conftest import TestSessionLocal
from tests.test_vn_turn_integration import seed_vn

URL = "/api/adventures/session-1/prose-evidence"
PLAYER_LINE = "I pocket the compass."
NARRATOR_LINE = "Lina kneels."


async def exchange(db, client, *, action=PLAYER_LINE, reply=NARRATOR_LINE, passes=None):
    user, avatar, state, _ = await seed_vn(db)
    if passes is not None:
        user.llm_settings = {**(user.llm_settings or {}), "prose_extraction_passes": passes}
    state.is_debug_enabled = True
    avatar.inventory = [{"id": "COMPASS", "name": "compass"}]
    before = await capture(db, state.session_id)
    sources = [
        ChatMessage(session_id=state.session_id, role=role, content=text)
        for role, text in (("user", action), ("assistant", reply))
    ]
    db.add_all(sources)
    await db.flush()
    replay = TurnReplay(
        session_id=state.session_id,
        before=before,
        input_text=action,
        assistant_id=sources[1].id,
        status="ready",
    )
    db.add(replay)
    # The live scene is now different. An item from the input must still bind
    # to the original identity even when a new one has the same display name.
    avatar.inventory = [{"id": "REPLACEMENT", "name": "compass"}]
    await db.commit()
    client.headers["Authorization"] = f"Bearer {create_user_access_token(user)}"
    return replay, sources, state, avatar


def install_model(monkeypatch, failing=(), during_inference=None):
    calls = []

    async def respond(_, prompt, schema, model, *, phase, **kwargs):
        calls.append((phase, prompt))
        if during_inference:
            await during_inference(phase)
        if phase in failing:
            raise TimeoutError("private provider detail")
        if phase == "user":
            quote, attrs = (
                "I pocket the compass",
                {
                    "kind": "custody",
                    "actor_id": "__player__",
                    "performer_id": "__player__",
                    "item_mention": "compass",
                    "value": "picked_up",
                },
            )
        else:
            quote, attrs = (
                "Lina kneels",
                {"kind": "posture", "actor_id": "LINA", "value": "kneeling"},
            )
        return schema.model_validate(
            {"extractions": [{"event": quote, "event_attributes": {"passage_id": "p0", **attrs}}]}
        )

    model = SimpleNamespace(model="local", max_tokens=5000, aexecute_complex_task=respond)
    monkeypatch.setattr(route, "GameMasterLLM", SimpleNamespace(for_role=lambda *args: model))
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("passes", [1, 2, 3])
async def test_review_through_http_uses_separate_sources_and_pre_turn_identities(
    client, monkeypatch, passes
):
    calls = install_model(monkeypatch)
    async with TestSessionLocal() as db:
        replay, messages, state, avatar = await exchange(db, client, passes=passes)
        original = (
            deepcopy(replay.before),
            deepcopy(state.entity_states),
            deepcopy(avatar.inventory),
        )
        response = await client.post(URL)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["has_snapshot"] is True
        assert [s["message_id"] for s in report["sources"]] == [m.id for m in messages]
        assert [s["revision_id"] for s in report["sources"]] == [m.revision_id for m in messages]
        for source in report["sources"]:
            assert len(source["events"]) == 1
            assert source["completed_passes"] == source["requested_passes"] == passes
        player, narrator = (s["events"][0] for s in report["sources"])
        assert (player["item_id"], narrator["actor_id"]) == ("COMPASS", "LINA")
        assert all(row["resolved"] for row in (player, narrator))
        assert [(row["start"], row["end"]) for row in (player, narrator)] == [(0, 20), (0, 11)]
        assert [phase for phase, _ in calls] == ["user"] * passes + ["assistant"] * passes
        assert all(NARRATOR_LINE not in prompt for _, prompt in calls[:passes])
        assert all(PLAYER_LINE not in prompt for _, prompt in calls[passes:])
        assert not any(
            secret in str(calls)
            for secret in ("HIDDEN_RING", "Hidden ring", "SECRET_GOAL", "ABSENT")
        )
        await db.refresh(replay)
        await db.refresh(state)
        await db.refresh(avatar)
        assert (replay.before, state.entity_states, avatar.inventory) == original
        assert len((await db.scalars(select(ChatMessage))).all()) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "broken",
    [
        "missing",
        "snapshot_owner",
        "snapshot_session",
        "snapshot_avatar",
        "foreign_entity",
        "assistant_id",
        "input_text",
        "wrong_boundary",
        "malformed",
    ],
)
async def test_unbound_snapshots_do_not_expose_current_or_foreign_ids(client, monkeypatch, broken):
    calls = install_model(monkeypatch)
    async with TestSessionLocal() as db:
        replay, messages, *_ = await exchange(db, client)
        before = deepcopy(replay.before)
        if broken == "missing":
            await db.delete(replay)
        elif broken == "input_text":
            replay.input_text = "An earlier turn."
        elif broken == "assistant_id":
            replay.assistant_id = "earlier-response"
        elif broken == "snapshot_owner":
            before["user_id"] = "another-user"
        elif broken == "snapshot_session":
            before["state"]["session_id"] = "another-session"
        elif broken == "snapshot_avatar":
            before["avatar"]["id"] = "another-avatar"
        elif broken == "foreign_entity":
            before["tables"]["world_entities"][0]["session_id"] = "another-session"
        elif broken == "malformed":
            before["state"] = []
        else:
            before["boundary"] = {
                "id": messages[0].id,
                "created_at": messages[0].created_at.isoformat(),
            }
        replay.before = before
        await db.commit()
    result = await client.post(URL)
    assert result.status_code == 200
    report = result.json()
    assert report["has_snapshot"] is False
    assert [s["events"][0]["resolved"] for s in report["sources"]] == [False, False]
    assert all("Лина" not in prompt for _, prompt in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "status"),
    [
        ("no_debug", 403),
        ("other_user", 404),
        ("command", 409),
        ("legacy_debug", 409),
        ("pending", 409),
        ("executing", 409),
        ("unanswered", 409),
        ("oversized", 422),
    ],
)
async def test_review_requires_owner_debug_and_a_completed_story_exchange(
    client, monkeypatch, scenario, status
):
    from backend.models.user import User

    calls = install_model(monkeypatch)
    monkeypatch.setattr(route.settings, "TALEWEAVER_DEBUG_ENABLED", False)
    action = {
        "command": "/imagine",
        "legacy_debug": "  /DeBuG actors",
        "oversized": "x" * 12001,
    }.get(scenario, PLAYER_LINE)
    async with TestSessionLocal() as db:
        replay, _, state, _ = await exchange(db, client, action=action)
        if scenario == "no_debug":
            state.is_debug_enabled = False
        elif scenario == "other_user":
            stranger = User(username="different-owner", hashed_password="unused")
            db.add(stranger)
            await db.flush()
            client.headers["Authorization"] = f"Bearer {create_user_access_token(stranger)}"
        elif scenario in {"pending", "executing"}:
            replay.status = scenario
        elif scenario == "unanswered":
            db.add(ChatMessage(session_id="session-1", role="user", content="Next turn"))
        await db.commit()
    assert (await client.post(URL)).status_code == status
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failing", [("user",), ("assistant",), ("user", "assistant")])
async def test_provider_failure_preserves_other_source_and_sanitizes_error(
    client, monkeypatch, failing
):
    calls = install_model(monkeypatch, failing)
    async with TestSessionLocal() as db:
        await exchange(db, client)
    response = await client.post(URL)
    assert "private provider detail" not in response.text
    assert [phase for phase, _ in calls] == ["user", "assistant"]
    if len(failing) == 2:
        assert response.status_code == 504
        return
    assert response.status_code == 200
    sources = {s["role"]: s for s in response.json()["sources"]}
    assert sources[failing[0]]["events"] == []
    assert "timed out" in sources[failing[0]]["error"]
    success = sources[("user" if "assistant" in failing else "assistant")]
    assert success["events"][0]["resolved"] and "error" not in success


def test_candidate_ids_preserve_player_access_and_omit_hidden_inventory_and_covered_layers():
    from backend.engine.prose_evidence_catalog import visible_catalog
    from tests.observable_state_support import world

    manager, rows = world()
    manager.state.entity_states = {"other": {"name": "Renamed NPC"}}
    manager.avatar.inventory.append({"id": "MALFORMED", "name": 42})
    actors, items = visible_catalog(manager, rows)
    assert actors["other"] == "Renamed NPC"
    assert "MALFORMED" not in items
    assert {"KEY", "BELL", "OTHER_COAT", "PLAYER_BAG_SECRET", "PLAYER_COAT"} <= items.keys()
    assert (
        not {"OTHER_INNER", "OTHER_BAG_SECRET", "LINING", "CONCEALED", "HIDDEN", "AWAY"}
        & items.keys()
    )


@pytest.mark.asyncio
async def test_game_can_advance_during_review_but_result_keeps_captured_revisions(
    client, monkeypatch
):
    async with TestSessionLocal() as db:
        _, messages, *_ = await exchange(db, client)
        ids = [(m.id, m.revision_id) for m in messages]

    async def continue_playing(phase):
        # A revision may be replaced immediately after capture. Both model
        # requests must still refer to the same historical exchange.
        with session_write_lease("session-1"):
            if phase == "user":
                async with TestSessionLocal() as other_db:
                    saved = await other_db.get(ChatMessage, ids[1][0])
                    saved.content = "A different narration."
                    saved.revision_id = "new-revision"
                    await other_db.commit()

    calls = install_model(monkeypatch, during_inference=continue_playing)
    with session_write_lease("session-1"):
        assert (await client.post(URL)).status_code == 409
    assert calls == []
    response = await client.post(URL)
    assert response.status_code == 200
    sources = response.json()["sources"]
    assert [(source["message_id"], source["revision_id"]) for source in sources] == ids
    assert sources[1]["events"][0]["quote"] == "Lina kneels"
    assert NARRATOR_LINE in calls[1][1]
    assert "A different narration." not in calls[1][1]
