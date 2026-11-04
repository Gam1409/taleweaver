"""Turn-local prose focus, independent of content rating and narrative genre."""


def narration_focus(*, scene_changed: bool, inspection_requested: bool) -> str:
    if inspection_requested:
        setting = (
            "INSPECTION REQUEST: Describe the requested surroundings or details concretely, "
            "within what the protagonist can perceive. Prioritize information useful to the request."
        )
    elif scene_changed:
        setting = (
            "SCENE ARRIVAL: Orient the player with the relevant visible layout and landmarks, "
            "then continue the action. An arrival does not require a panoramic digression."
        )
    else:
        setting = (
            "CONTINUING SCENE: Default to dialogue, actions and their consequences. "
            "Omit unchanged surroundings, weather, ambient sound, clothing and bodily-state recaps. "
            "Honor an explicit request for description in any language even without an inspection marker. "
            "Otherwise mention a detail only if it changes, is directly interacted with, or is necessary "
            "to understand this action. Do not invent an environmental change just to add atmosphere."
        )
    return (
        "PROSE FOCUS FOR THIS TURN:\n" + setting + "\n"
        "After dialogue or a gesture conveys a feeling, do not paraphrase that feeling in a "
        "second explanation. Avoid panoramic cutaways to the city, distant lives or the outside "
        "world as an automatic ending. Do not turn each exchange into a claim of destiny, "
        "irreversible transformation or total devotion. Keep meaningful nuance and new reactions; "
        "no fixed length or mandatory narrator paragraph is required. Stop when this turn's "
        "action and response are complete, without an atmospheric closing paragraph."
    )
