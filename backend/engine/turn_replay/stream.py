"""Run a complete replay under the normal turn lease, restoring on failure."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any

from anyio import CancelScope
from sqlalchemy import select

from backend.engine.turn_replay import service
from backend.models.chat import ChatMessage


async def history_event(manager: Any, content: str | None = None) -> str:
    messages = list(
        await manager.db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == manager.game_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
    )
    data = {"messages": [message.to_client_dict() for message in messages], "content": content}
    return f"event: replay_history\ndata: {json.dumps(data)}\n\n"


async def run(
    manager: Any,
    message: str,
    auto_visualize: bool,
    language: str | None,
    replay_id: str | None,
    hooks: Any,
) -> AsyncGenerator[str, None]:
    succeeded = False
    error = None
    try:
        await service.recover_owned(manager)
        if replay_id:
            message = await service.begin(manager, replay_id)
            yield await history_event(manager, message)
        async with aclosing(
            with_hooks(manager, message, auto_visualize, language, hooks)
        ) as stream:
            async for chunk in stream:
                if replay_id and replay_failed(chunk):
                    error = (
                        chunk
                        if chunk.startswith("event: error")
                        else 'event: error\ndata: {"detail":"The new response was incomplete. The previous turn was restored."}\n\n'
                    )
                    break
                if chunk.startswith("event: final"):
                    await service.finish(manager)
                    succeeded = True
                yield chunk
    except (asyncio.CancelledError, GeneratorExit):
        raise
    except service.ReplayUnavailableError as exc:
        error = f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
    finally:
        if getattr(manager, "_replaying", False) and not succeeded:
            # The backup remains durable if the process dies during cleanup.
            with CancelScope(shield=True):
                await manager.db.rollback()
                await service.recover(manager.db, manager.game_id)
                await manager.db.refresh(manager.user)
                manager.state = manager.avatar = manager.adventure = None
    if error:
        if getattr(manager, "_replaying", False):
            yield await history_event(manager)
        yield error


async def with_hooks(
    manager: Any, message: str, auto_visualize: bool, language: str | None, hooks: Any
) -> AsyncGenerator[str, None]:
    async with aclosing(manager._process_turn_inner(message, auto_visualize, language)) as stream:
        async for chunk in stream:
            if not chunk.startswith("event: final"):
                yield chunk
                continue
            async with aclosing(hooks.process_final(chunk)) as finalized:
                async for result in finalized:
                    yield result


def replay_failed(chunk: str) -> bool:
    if chunk.startswith("event: error"):
        return True
    if not chunk.startswith("event: final"):
        return False
    data = json.loads(chunk.split("data: ", 1)[1])
    return bool(data.get("narration_incomplete"))
