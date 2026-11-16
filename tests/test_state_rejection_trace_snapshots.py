"""State boundary evidence includes sanctioned actor/progress fields without ORM loads."""

from types import SimpleNamespace

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session

from backend.core.engine_detailed_trace import changes, state_of
from backend.models.avatar import Avatar
from backend.models.session_state import SessionState


def test_snapshot_and_diff_cover_avatar_quest_sequence_and_rule_state():
    state = SimpleNamespace(
        inventory=[],
        discovered_scenes=["START"],
        quests=[{"id": "quest", "status": "active"}],
        world_memories=[{"text": "Neutral memory"}],
        world_rumors=[{"text": "Neutral rumor"}],
        active_sequence_id="first",
        active_sequence_order=1,
        plot="Neutral plot",
        rules="Neutral rule",
        completed_condition="quest.complete",
        gameover_condition="hp.zero",
        completed_guard_expression="quest.complete",
        gameover_guard_expression="hp.zero",
        allow_dynamic_items=False,
    )
    avatar = SimpleNamespace(
        id="fixture-avatar",
        hp=10,
        max_hp=10,
        stamina=8,
        max_stamina=8,
        mana=5,
        max_mana=5,
        exp=0,
        stats={"strength": 10},
        inventory=[{"id": "item"}],
        equipment={"MainHand": "item"},
        status_effects=[],
    )
    manager = SimpleNamespace(state=state, avatar=avatar)
    before = state_of(manager)
    assert before["quests"] == [{"id": "quest", "status": "active"}]
    assert before["world_memories"] == [{"text": "Neutral memory"}]
    assert before["avatar"]["inventory"] == [{"id": "item"}]
    state.quests[0]["status"] = "complete"
    state.active_sequence_order = 2
    avatar.hp = 7
    avatar.inventory.clear()
    changed = changes(before, state_of(manager))
    assert changed["quests"]["before"][0]["status"] == "active"
    assert changed["quests"]["after"][0]["status"] == "complete"
    assert changed["active_sequence_order"] == {"before": 1, "after": 2}
    assert changed["avatar"]["before"]["hp"] == 10
    assert changed["avatar"]["after"]["hp"] == 7
    assert before["avatar"]["inventory"] == [{"id": "item"}]


def test_snapshot_whitelist_never_reads_account_settings_or_relationship_properties():
    class ForbiddenFields:
        @property
        def user(self):
            raise AssertionError("Account relationship must not be inspected")

        @property
        def settings(self):
            raise AssertionError("Account settings must not be inspected")

    state, avatar = ForbiddenFields(), ForbiddenFields()
    state.quests = []
    avatar.hp = 8
    avatar.password = "synthetic-secret"
    avatar.encrypted_api_keys = {"fixture": "synthetic-secret"}
    snapshot = state_of(SimpleNamespace(state=state, avatar=avatar))
    assert snapshot == {"quests": [], "avatar": {"hp": 8}}
    assert "synthetic-secret" not in str(snapshot)


def test_snapshot_skips_expired_columns_and_unloaded_orm_relationships():
    engine = create_engine("sqlite://")
    Avatar.__table__.create(engine)
    SessionState.__table__.create(engine)
    try:
        with Session(engine, expire_on_commit=False) as db:
            avatar = Avatar(
                id="fixture-avatar",
                user_id="fixture-user",
                name="Neutral actor",
                hp=10,
                inventory=[{"id": "item"}],
            )
            state = SessionState(
                id="fixture-state",
                session_id="fixture-session",
                quests=[{"id": "quest"}],
                rules="Neutral rule",
            )
            db.add_all([avatar, state])
            db.commit()
            db.expire(avatar, ["hp"])
            db.expire(state, ["rules", "inventory"])
            assert "session" in inspect(state).unloaded
            queries = []

            @event.listens_for(engine, "before_cursor_execute")
            def observe(*_args):
                queries.append(True)

            snapshot = state_of(SimpleNamespace(state=state, avatar=avatar))
            assert queries == []
            assert "hp" not in snapshot["avatar"]
            assert "rules" not in snapshot
            assert "inventory" not in snapshot
            assert snapshot["avatar"]["inventory"] == [{"id": "item"}]
            assert snapshot["quests"] == [{"id": "quest"}]
            assert "session" not in snapshot
    finally:
        engine.dispose()
