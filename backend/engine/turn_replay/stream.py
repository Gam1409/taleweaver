"""Run a complete replay under the normal turn lease, restoring on failure."""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any

from anyio import CancelScope
from sqlalchemy import select

from backend.engine.chpm.kernel import ChpmError
from backend.engine.turn_replay import drafts, service
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


def with_input_receipt(chunk: str, manager: Any) -> str:
    input_id = getattr(manager, "_vn_player_message_id", None)
    if not isinstance(input_id, str) or not input_id:
        return chunk
    payload = json.loads(chunk.split("data: ", 1)[1])
    payload["saved_user_message_id"] = input_id
    return f"event: final\ndata: {json.dumps(payload)}\n\n"


async def run(
    manager: Any,
    message: str,
    auto_visualize: bool,
    language: str | None,
    replay_id: str | None,
    hooks: Any,
) -> AsyncGenerator[str, None]:
    """Hold CHPM narration until the inner runner commits its recovery boundary."""
    manager._chpm_turn = None
    manager._committed_response_id = None
    manager._visible_narration_draft = ""
    manager._visible_narration_truncated = False
    manager._chpm_publish_after_commit = False
    held: list[str] = []
    async with aclosing(
        _run(manager, message, auto_visualize, language, replay_id, hooks)
    ) as stream:
        async for chunk in stream:
            if _hold_chunk(manager, chunk):
                held.append(chunk)
                continue
            if chunk.startswith("event: final"):
                for item in held:
                    yield item
                held.clear()
            yield chunk


def _hold_chunk(manager: Any, chunk: str) -> bool:
    return chunk.startswith("event: chunk") and bool(
        getattr(manager, "_chpm_publish_after_commit", False)
    )


async def _run(
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
                outgoing = chunk
                if chunk.startswith("event: error") or (replay_id and replay_failed(chunk)):
                    error = (
                        chunk
                        if chunk.startswith("event: error")
                        else 'event: error\ndata: {"detail":"The new response was incomplete. The previous turn was restored."}\n\n'
                    )
                    break
                if chunk.startswith("event: final"):
                    await service.finish(manager)
                    outgoing = with_input_receipt(chunk, manager)
                    succeeded = True
                yield outgoing
    except (asyncio.CancelledError, GeneratorExit):
        raise
    except (service.ReplayUnavailableError, ChpmError) as exc:
        error = f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
    finally:
        if (
            getattr(manager, "_replaying", False) or getattr(manager, "_recoverable_turn", False)
        ) and not succeeded:
            # The backup remains durable if the process dies during cleanup.
            with CancelScope(shield=True):
                await manager.db.rollback()
                await service.recover(manager.db, manager.game_id)
                await drafts.preserve(manager)
                await manager.db.refresh(manager.user)
                manager.state = manager.avatar = manager.adventure = None
    if error:
        if getattr(manager, "_replaying", False) or getattr(manager, "_recoverable_turn", False):
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
