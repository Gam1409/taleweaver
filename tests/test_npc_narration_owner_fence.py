"""A permissive semantic review cannot publish an exact current owner contradiction."""

import json
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.engine.chpm.state import KEY, load
from backend.engine.clothing.visuals import session_objects
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.scene_staging.commands import CommandProof, apply_command
from backend.engine.scene_staging.state import KEY as STAGING_KEY
from backend.engine.visual_novel.config import VnSettings, write_settings
from backend.engine.visual_novel.continuity import possession_snapshot
from backend.models.avatar import Avatar
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity
from tests.conftest import TestSessionLocal
from tests.state_response_fixture import extraction
from tests.test_chpm_host_turn import run
from tests.test_chpm_local_failure_turn import install
from tests.test_clothing_runtime import item, profile
from tests.test_npc_contested_item_turn import ITEM, seed
from tests.test_npc_narration_authority_scope import EmptyScopeRoles

CLAIMS = {
    "custody": "Лина держит латунную кружку.",
    "wardrobe": "Лина уже одета в синее пальто.",
    "pose": "Лина самостоятельно садится на месте.",
}


class ContradictionRoles(EmptyScopeRoles):
    def __init__(self, kind, *, item_changes=None, pose_changes=None):
        super().__init__()
        self.kind = kind
        self.item_changes = item_changes or {}
        self.pose_changes = pose_changes or {}
        self.claims_enabled = True
        self.accepted_reviews = 0

    @property
    def story(self):
        return super().story + ("\n" + CLAIMS[self.kind] if self.claims_enabled else "")

    def review(self, supplied):
        result = super().review(supplied)
        assert json.loads(result)["matches"] is True
        self.accepted_reviews += 1
        return result

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if not issubclass(schema, ItemExtraction):
            return await super().structured(*args, **kwargs)
        self.calls.append((schema.__name__, args, kwargs))
        if not self.claims_enabled:
            return extraction(schema)
        common = {
            "item_id": ITEM if self.kind == "custody" else "BLUE_COAT",
            "source_owner": "LINA",
            "destination_owner": "LINA",
            "disposition": "held" if self.kind == "custody" else "worn",
            "basis": "observed_possession" if self.kind == "custody" else "observed_wear",
            "evidence": CLAIMS[self.kind],
        }
        return extraction(
            schema,
            actions=[] if self.kind == "pose" else [common | self.item_changes],
            staging={
                "changes": [
                    {
                        "entity_id": "LINA",
                        "performer_id": "LINA",
                        "posture": "sitting",
                        "evidence": CLAIMS[self.kind],
                        **self.pose_changes,
                    }
                ]
                if self.kind == "pose"
                else [],
                "props": [],
                "explicit": [],
            }
            if self.kind == "pose"
            else None,
        )


async def configure_owner(db, state, kind):
    npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
    npc.inventory = [item("BLUE_COAT")]
    npc.visual_profile = profile()
    if kind == "pose":
        write_settings(state, VnSettings(scene_staging=True))
        state.entity_states = apply_command(
            state.entity_states,
            actor_id="LINA",
            scene_id="START",
            cast=[{"id": actor, "name": actor} for actor in ("LINA", "MILA")],
            proof=CommandProof(
                command_id="old-pose",
                actor_id="LINA",
                scene_id="START",
                input_id="old-input",
                input_revision="old-revision",
                request_hash=sha256(b"old pose request").hexdigest(),
                operation="set_pose",
            ),
            enabled=True,
            posture="standing",
        )
    await db.commit()


@pytest.mark.parametrize("kind", ["custody", "wardrobe", "pose"])
async def test_current_owner_contradiction_blocks_already_reviewed_prose_and_rolls_back(
    monkeypatch, kind
):
    roles = ContradictionRoles(kind)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, "json")
        await configure_owner(db, state, kind)
        before = deepcopy(state.entity_states)
        before_time = state.in_game_time
        _, events = await run(db, user, "Я молча жду, ничего не меняя.")
        assert roles.accepted_reviews == 1
        assert any(row.startswith("event: error") for row in events), "".join(events)
        assert not any(row.startswith("event: chunk") for row in events), "".join(events)
        assert not any(row.startswith("event: final") for row in events), "".join(events)
        await db.refresh(state)
        assert state.entity_states == before
        assert state.in_game_time == before_time
        assert load(state).actors == {}
        rows = await session_objects(db, state.session_id)
        avatar = await db.get(Avatar, state.avatar_id)
        possessions = possession_snapshot(SimpleNamespace(state=state, avatar=avatar), rows)
        assert possessions.owners[ITEM] == "__scene__"
        assert possessions.owners["BLUE_COAT"] == "LINA"
        npc = next(row for row in rows if row.id == "LINA")
        assert not npc.visual_profile["worn"]
        if kind == "pose":
            assert (
                state.entity_states[STAGING_KEY]["actors"]["LINA"]["posture"]["value"] == "standing"
            )
        replies = list(
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == state.session_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.content == roles.story,
                )
            )
        )
        assert replies == []
        assert KEY in state.entity_states


@pytest.mark.parametrize(
    "variant", ["old_wear", "uncertain", "uncontrolled", "unknown_performer", "external_pose"]
)
async def test_late_fence_preserves_known_ordinary_uncertain_and_external_cases(
    monkeypatch, variant
):
    pose = variant in {"unknown_performer", "external_pose"}
    item_changes = {"basis": "claim"} if variant == "uncertain" else {}
    pose_changes = {"performer_id": None}
    if variant == "external_pose":
        pose_changes = {
            "performer_id": "__player__",
            "cause": {
                "kind": "current_player_action",
                "basis": "resolved_external_effect",
                "passage_id": "player:p0",
            },
        }
    roles = ContradictionRoles(
        "pose" if pose else "wardrobe", item_changes=item_changes, pose_changes=pose_changes
    )
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, "json")
        await configure_owner(db, state, roles.kind)
        npc = await db.scalar(select(WorldEntity).where(WorldEntity.id == "LINA"))
        if variant == "old_wear":
            npc.visual_profile = profile("BLUE_COAT")
        if variant == "uncontrolled":
            current = load(state)
            current.settings.actor_ids = ["MILA"]
            state.entity_states = {**state.entity_states, KEY: current.model_dump()}
        await db.commit()
        text = "Я помогаю Лине сесть." if variant == "external_pose" else "Я молча жду."
        _, events = await run(db, user, text)
        assert roles.accepted_reviews == 1
        assert any(row.startswith("event: final") for row in events), "".join(events)
        assert not any(row.startswith("event: error") for row in events), "".join(events)
        assert len([row for row in events if row.startswith("event: chunk")]) == 1
        await db.refresh(state)
        if pose:
            value = state.entity_states[STAGING_KEY]["actors"]["LINA"]["posture"]["value"]
            assert value == ("sitting" if variant == "external_pose" else "standing")
        else:
            actor = state.entity_states.get("LINA", {})
            worn = actor.get("visual_profile", npc.visual_profile)["worn"]
            assert bool(worn) == (variant != "uncertain")


async def test_rejected_owner_claim_does_not_leak_into_a_fresh_retry(monkeypatch):
    roles = ContradictionRoles("custody")
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, "json")
        await configure_owner(db, state, "custody")
        manager, first = await run(db, user, "Я молча жду.")
        assert any(row.startswith("event: error") for row in first), "".join(first)
        assert manager._npc_narration_fence is None
        first_attempt = manager._turn_control_attempt.id
        roles.claims_enabled = False
        second = [row async for row in manager.process_turn("Я молча жду.")]
        assert any(row.startswith("event: final") for row in second), "".join(second)
        assert not any(row.startswith("event: error") for row in second), "".join(second)
        assert first_attempt != manager._turn_control_attempt.id
        assert manager._npc_narration_fence is None
        assert roles.accepted_reviews == 2
        replies = list(
            await db.scalars(
                select(ChatMessage).where(
                    ChatMessage.session_id == state.session_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.content.contains(CLAIMS["custody"]),
                )
            )
        )
        assert replies == []


class TransferEchoRoles(EmptyScopeRoles):
    def __init__(self, false_current):
        super().__init__()
        self.false_current = false_current

    @property
    def story(self):
        return (
            super().story
            + "\nLina picks up the cup. Lina gives the cup to the traveler."
            + (" Lina still holds the cup." if self.false_current else "")
        )

    def requests_for(self, body, *, has_results):
        if not has_results and body["actor_id"] == "LINA":
            return [
                {"name": "take_item", "arguments": {"item_id": ITEM}},
                {"name": "give_item", "arguments": {"item_id": ITEM, "recipient_id": "@player"}},
            ]
        return super().requests_for(body, has_results=has_results)

    async def structured(self, *args, **kwargs):
        schema = kwargs.get("response_model") or args[2]
        if not issubclass(schema, ItemExtraction):
            return await super().structured(*args, **kwargs)
        actions = [
            {
                "item_id": ITEM,
                "source_owner": source,
                "destination_owner": destination,
                "disposition": "held",
                "basis": "completed",
                "evidence": quote,
            }
            for source, destination, quote in (
                ("__scene__", "LINA", "Lina picks up the cup."),
                ("LINA", "__player__", "Lina gives the cup to the traveler."),
            )
        ]
        if self.false_current:
            actions.append(
                {
                    "item_id": ITEM,
                    "source_owner": "LINA",
                    "destination_owner": "LINA",
                    "disposition": "held",
                    "basis": "observed_possession",
                    "evidence": "Lina still holds the cup.",
                }
            )
        return extraction(schema, actions=actions)


@pytest.mark.parametrize("false_current", [False, True])
async def test_intermediate_transfer_echoes_do_not_certify_a_contradictory_final_claim(
    monkeypatch, false_current
):
    roles = TransferEchoRoles(false_current)
    install(monkeypatch, roles)
    async with TestSessionLocal() as db:
        user, state = await seed(db, "json")
        _, events = await run(db, user, "Я молча жду.")
        assert roles.reviews
        assert any(row.startswith("event: error") for row in events) == false_current, "".join(
            events
        )
        assert any(row.startswith("event: final") for row in events) != false_current, "".join(
            events
        )
        assert any(row.startswith("event: chunk") for row in events) != false_current, "".join(
            events
        )
        await db.refresh(state)
        avatar = await db.get(Avatar, state.avatar_id)
        rows = await session_objects(db, state.session_id)
        actual = possession_snapshot(SimpleNamespace(state=state, avatar=avatar), rows)
        assert actual.owners[ITEM] == ("__scene__" if false_current else "__player__")
