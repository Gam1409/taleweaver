"""Numeric console usage summaries, independent of opt-in raw telemetry."""

from typing import Any


def _count(value: Any) -> int:
    return int(value) if type(value) is int and 0 <= value <= 10**12 else 0


def print_token_usage(usage: Any, model: str, system: str, user: str, response: str) -> None:
    label = "TOKEN USAGE"
    if isinstance(usage, dict) and usage:
        prompt = _count(usage.get("prompt_tokens"))
        completion = _count(usage.get("completion_tokens"))
        total = _count(usage.get("total_tokens"))
    else:
        label, prompt, completion = _estimate(model, system, user, response)
        total = prompt + completion
    # Raw model names, phase strings and provider fields belong only in opt-in telemetry.
    print(
        f"\n>>> [{label}] Prompt: {prompt} | Completion: {completion} | Total: {total}\n",
        flush=True,
    )


def _estimate(model: str, system: str, user: str, response: str) -> tuple[str, int, int]:
    try:
        import litellm

        prompt = litellm.token_counter(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        completion = litellm.token_counter(model=model, text=response)
        return "TOKEN USAGE (ESTIMATED)", _count(prompt), _count(completion)
    except Exception:
        return "TOKEN USAGE (ESTIMATED FALLBACK)", len(system + user) // 4, len(response) // 4
