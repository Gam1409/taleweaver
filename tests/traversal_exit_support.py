"""Real scoped worlds for deterministic traversal tests; narration is always inert."""

from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine.gameplay.manager import GameTurnManager
from backend.models import (
    AdventureTemplate,
    Avatar,
    GameSession,
    SessionState,
    User,
    WorldExit,
    WorldScene,
)


@dataclass
class TraversalWorld:
    db: AsyncSession
    user: User
    template: AdventureTemplate
    sessions: dict[str, GameSession]
    states: dict[str, SessionState]
    avatars: dict[str, Avatar]
    template_exit: WorldExit
    exits: dict[str, WorldExit]

    def manager(self, session_id: str, monkeypatch: pytest.MonkeyPatch) -> GameTurnManager:
        manager = GameTurnManager(self.db, session_id, self.user)
        manager.state = self.states[session_id]
        manager.avatar = self.avatars[session_id]
        manager.adventure = self.template

        async def narrate(*_args, **_kwargs):
            yield 'event: chunk\ndata: {"content":"The destination is quiet."}\n\n'

        monkeypatch.setattr(manager, "_run_llm_cycle", narrate)
        return manager


async def add_session(db: AsyncSession, session_id: str, template: AdventureTemplate, user: User):
    avatar = Avatar(
        id=f"avatar-{session_id}",
        user_id=user.id,
        template_id=template.id,
        name="Ari",
        hp=20,
        inventory=[],
        stats={},
    )
    db.add(avatar)
    await db.flush()
    session = GameSession(
        id=session_id,
        user_id=user.id,
        avatar_id=avatar.id,
        template_id=template.id,
        adventure_title=template.title,
        status="active",
    )
    db.add(session)
    await db.flush()
    state = SessionState(
        session_id=session_id,
        user_id=user.id,
        avatar_id=avatar.id,
        template_id=template.id,
        current_scene_id="START",
        entity_states={},
        exit_states={},
    )
    db.add(state)
    await db.flush()
    return session, state, avatar


def passage(**fields) -> WorldExit:
    return WorldExit(
        from_scene_id="START",
        to_scene_id="END",
        label="Workbench passage",
        lock_description="The session passage is locked.",
        **fields,
    )


async def seed_traversal_world(
    db: AsyncSession,
    *,
    template_locked: bool = True,
    current_locked: bool = False,
    template_type: str = "bidirectional",
    current_type: str = "bidirectional",
) -> TraversalWorld:
    user = User(id="traversal-owner", username="traversal-owner", hashed_password="unused")
    db.add(user)
    await db.flush()
    template = AdventureTemplate(id="traversal-template", owner_id=user.id, title="Workbench study")
    db.add(template)
    await db.flush()
    sessions, states, avatars = {}, {}, {}
    for session_id in ("one", "two"):
        sessions[session_id], states[session_id], avatars[session_id] = await add_session(
            db, session_id, template, user
        )
    for scope in ({"template_id": template.id}, {"session_id": "one"}, {"session_id": "two"}):
        for scene_id in ("START", "END"):
            db.add(
                WorldScene(
                    id=scene_id, label=scene_id.title(), description="A quiet workroom.", **scope
                )
            )
    template_exit = passage(
        id="00-template-exit",
        template_id=template.id,
        is_locked=template_locked,
        exit_type=template_type,
        on_exit_used_script="tw.vars.set('passage_source', 'template')",
    )
    db.add(template_exit)
    await db.flush()
    exits = {}
    for session_id in ("one", "two"):
        exits[session_id] = passage(
            id=f"10-{session_id}-exit",
            session_id=session_id,
            is_locked=current_locked if session_id == "one" else not current_locked,
            exit_type=current_type,
            code_to_unlock=f"{session_id}-code",
            unlock_expression=f"tw.vars.get('{session_id}_permit', False)",
            on_open_exit_script=f"tw.vars.set('opened_source', '{session_id}')",
            on_exit_used_script=f"tw.vars.set('passage_source', '{session_id}')",
            on_exit_used_text=f"Passage used in session {session_id}.",
        )
        db.add(exits[session_id])
    await db.commit()
    return TraversalWorld(db, user, template, sessions, states, avatars, template_exit, exits)


async def traverse(
    world: TraversalWorld, session_id: str, exit_ref: str, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    manager = world.manager(session_id, monkeypatch)
    return [chunk async for chunk in manager.interactions._handle_traverse_exit(exit_ref)]
