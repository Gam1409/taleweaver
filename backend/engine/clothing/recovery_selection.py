"""Only explicitly selected, previously validated recovery entries may be applied."""


def selected_entries(preview: dict, selection: str | None) -> set[int]:
    accepted = preview.get("accepted") or []
    allowed = {row["proposal_index"] for row in accepted if type(row.get("proposal_index")) is int}
    if not accepted:
        raise ValueError("Preview has rejected or empty changes; nothing was applied.")
    if len(allowed) != len(accepted):
        raise ValueError("This preview predates item selection. Generate a new preview.")
    if selection is None:
        if preview.get("manual_indices"):
            raise ValueError(
                "Manual recovery proposals require explicit selection before applying."
            )
        if any(row.get("source_role") == "user" for row in accepted):
            raise ValueError(
                "Player-sourced corrections require explicit selection before applying."
            )
        if preview.get("errors"):
            raise ValueError(
                "Preview has rejected changes. Select the validated garments to apply; nothing was applied."
            )
        return (
            allowed  # Older clients may apply an entirely validated preview with its exact token.
        )
    if len(selection) > 64:
        raise ValueError("Selection is too long; generate a new preview if necessary.")
    values = selection.split(",")
    if not 1 <= len(values) <= 16 or any(
        not value.isascii() or not value.isdecimal() for value in values
    ):
        raise ValueError("Select one or more validated garment entries.")
    selected = {int(value) for value in values}
    if len(selected) != len(values) or not selected.issubset(allowed):
        raise ValueError(
            "Selection includes duplicate, rejected or unknown entries; nothing was applied."
        )
    return selected
