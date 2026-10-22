"""Typed LLM errors that carry diagnostics for user-facing messages and server logs."""

from __future__ import annotations

from typing import Any, Optional

_CATEGORY_LABELS = {
    "small": "Small Model",
    "complex": "Complex Model",
    "generator": "World Generator",
    "compression": "Compression Model",
}

# A cutoff far below the configured budget means the provider capped the output itself.
_PROVIDER_CAP_RATIO = 0.9


class LLMTruncatedResponseError(ValueError):
    """The model stopped before finishing its answer (output token limit reached)."""

    def __init__(self, message: str, diagnostics: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.diagnostics: dict[str, Any] = diagnostics or {}


def _usage_value(usage: Any, key: str) -> Optional[int]:
    if usage is None:
        return None
    value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
    return value if isinstance(value, int) else None


def _reasoning_tokens(usage: Any) -> Optional[int]:
    if usage is None:
        return None
    details = (
        usage.get("completion_tokens_details")
        if isinstance(usage, dict)
        else getattr(usage, "completion_tokens_details", None)
    )
    return _usage_value(details, "reasoning_tokens")


def collect_truncation_diagnostics(
    response: Any, *, model_category: str, provider: str, max_tokens: int
) -> dict[str, Any]:
    """Extracts model, budget and actual token usage from a completion response."""
    choices = getattr(response, "choices", None) or [None]
    usage = getattr(response, "usage", None)
    model = getattr(response, "model", None)
    return {
        "model_category": model_category,
        "category_label": _CATEGORY_LABELS.get(model_category, model_category),
        "provider": provider,
        "model": model if isinstance(model, str) else None,
        "max_tokens": max_tokens,
        "finish_reason": getattr(choices[0], "finish_reason", None),
        "prompt_tokens": _usage_value(usage, "prompt_tokens"),
        "completion_tokens": _usage_value(usage, "completion_tokens"),
        "reasoning_tokens": _reasoning_tokens(usage),
    }


def _describe_usage(diag: dict[str, Any]) -> str:
    completion = diag.get("completion_tokens")
    if completion is None:
        return "Actual output token count was not reported by the provider."
    reasoning = diag.get("reasoning_tokens")
    reasoning_part = f" (incl. {reasoning} reasoning tokens)" if reasoning else ""
    return f"The model stopped after {completion} output tokens{reasoning_part}."


def _provider_cap_hint(diag: dict[str, Any]) -> str:
    completion = diag.get("completion_tokens")
    budget = diag.get("max_tokens") or 0
    if completion is None or not budget or completion >= budget * _PROVIDER_CAP_RATIO:
        return ""
    return (
        " This is well below the configured limit, so the provider or model probably "
        "enforces a lower output cap."
    )


def build_truncation_message(diag: dict[str, Any]) -> str:
    """Human-readable message; keeps the phrase 'token limit' for error classifiers."""
    label = diag.get("category_label") or "LLM"
    model = diag.get("model") or "unknown model"
    return (
        f"LLM response was truncated (token limit). {label} '{model}' "
        f"(limit: {diag.get('max_tokens')} tokens, finish_reason: {diag.get('finish_reason')}). "
        f"{_describe_usage(diag)}{_provider_cap_hint(diag)} "
        f"Increase '{label}' max tokens in Settings (Intelligence) and retry."
    )


def build_truncation_error(
    response: Any, *, model_category: str, provider: str, max_tokens: int
) -> LLMTruncatedResponseError:
    diagnostics = collect_truncation_diagnostics(
        response, model_category=model_category, provider=provider, max_tokens=max_tokens
    )
    return LLMTruncatedResponseError(build_truncation_message(diagnostics), diagnostics)
