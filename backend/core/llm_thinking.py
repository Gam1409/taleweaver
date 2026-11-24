"""Provider thinking controls, including OpenAI-compatible wire extensions."""

from typing import Any


def apply_thinking_settings(
    kwargs: dict[str, Any],
    *,
    provider: str,
    model: str,
    enabled: bool,
    budget_tokens: int,
    role: str = "",
) -> None:
    """Keep native controls on the adapter path that preserves them on the wire."""
    if (
        provider == "custom_openai"
        and role == "compression"
        and not enabled
        and model.lower().removeprefix("openai/").startswith("koboldcpp/")
    ):
        extra_body = kwargs.setdefault("extra_body", {})
        template = extra_body.get("chat_template_kwargs", {})
        extra_body["chat_template_kwargs"] = {**template, "enable_thinking": False}
        return
    if provider == "minimax":
        normalized = model.rsplit("/", 1)[-1].casefold()
        if normalized != "minimax-m3" and not normalized.startswith("minimax-m3-"):
            # Earlier MiniMax families always reason and ignore the M3 switch.
            return
        kwargs["extra_body"] = {
            **kwargs.get("extra_body", {}),
            "thinking": {"type": "adaptive" if enabled else "disabled"},
        }
        return
    if provider == "deepseek":
        kwargs["thinking"] = {"type": "enabled" if enabled else "disabled"}
        return
    if enabled:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget_tokens}
