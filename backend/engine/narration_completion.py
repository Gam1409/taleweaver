"""Explain incomplete, committed narration without inviting duplicate game actions."""

INTERRUPTED_WARNING = (
    "The model connection ended before the narration completed. "
    "The received text and turn were saved. Do not repeat the same action to recover the ending."
)


def finish_warning(reason: str | None) -> str | None:
    if reason == "length":
        return (
            "The narration reached the model's output limit. The received text and turn were saved. "
            "Increase the narration token limit for future replies."
        )
    if reason == "content_filter":
        return "The provider stopped the narration. The received text and turn were saved."
    return None
