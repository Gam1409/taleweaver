"""Small operation-specific functions; the host supplies actor and session authority."""

from backend.engine.npc_actions.contracts import ACTION_MODELS

DESCRIPTIONS = {
    "move_to": "Stage your travel along a permitted current-room route. Ends this scene's action plan.",
    "take_item": "Stage taking an accessible loose item. Its canonical ID and properties are preserved.",
    "put_down_item": "Stage putting down an item you carry; optional position describes its placement.",
    "give_item": "Stage giving your carried item to a present recipient. No voluntary recipient response is implied.",
    "wear_item": "Stage fully wearing an owned garment.",
    "take_off_item": "Stage removing your worn garment; you keep carrying it.",
    "adjust_clothing": "Stage the final uncovered regions of your worn garment; it remains worn. Empty restores full coverage.",
    "change_item_state": "Stage a current descriptive property of your item. Cannot change identity, mechanics or create abilities.",
    "use_item": "Stage partial/full use of your item; describe remaining state when relevant. No invented numeric effects.",
    "discard_actions": "Discard this whole unsubmitted action plan. Does not undo memory/notebook operations.",
}


def definitions(names: set[str]) -> list[dict]:
    result = []
    for name, model in ACTION_MODELS.items():
        if name not in names:
            continue
        schema = model.model_json_schema()
        schema.pop("title", None)
        schema["properties"].pop("tool")
        schema["required"] = [key for key in schema.get("required", []) if key != "tool"]
        for value in schema["properties"].values():
            value.pop("title", None)
        result.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": DESCRIPTIONS[name],
                    "parameters": schema,
                    "strict": False,
                },
            }
        )
    return result
