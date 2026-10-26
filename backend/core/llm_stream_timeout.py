"""Bound provider silence without disguising an interrupted response as complete."""

import asyncio
from typing import Any


async def with_stream_timeout(stream: Any, *, initial_timeout: float, chunk_timeout: float):
    has_content = False
    finished = False
    iterator = aiter(stream)
    while True:
        timeout = chunk_timeout if has_content else initial_timeout
        try:
            chunk = await asyncio.wait_for(anext(iterator), timeout=timeout)
        except StopAsyncIteration:
            return
        except TimeoutError:
            if finished:
                return
            detail = (
                "The AI response stopped arriving before completion."
                if has_content
                else "The AI model did not respond in time."
            )
            raise TimeoutError(detail) from None
        except Exception:
            if finished:
                return
            raise
        choices = getattr(chunk, "choices", None)
        if choices:
            delta = getattr(getattr(choices[0], "delta", None), "content", None)
            has_content = has_content or bool(isinstance(delta, str) and delta.strip())
            finished = finished or bool(getattr(choices[0], "finish_reason", None))
        yield chunk
