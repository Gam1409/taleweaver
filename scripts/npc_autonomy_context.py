"""Authored local knowledge and bounded firsthand memory for the workshop pilot."""

import json


def update_notebook(current, edit):
    """A resident edits a private page by title; empty text removes that page."""
    if not isinstance(edit, dict) or set(edit) != {"title", "text"}:
        raise ValueError("A notebook edit requires title and text")
    title, text = edit["title"], edit["text"]
    if not isinstance(title, str) or not title.strip() or len(title) > 64:
        raise ValueError("Invalid page title")
    if not isinstance(text, str) or len(text) > 600:
        raise ValueError("Invalid page text")
    pages = current.copy()
    if text:
        pages[title] = text
    else:
        pages.pop(title, None)
    if len(pages) > 12:
        raise ValueError("Notebook full")
    return pages


PROFILES = {
    "Lina": {
        "background": "A former sign painter, now drawing the neighbourhood before it changes.",
        "tension": "She enjoys company while sketching but dislikes being watched before a drawing takes shape.",
        "relationship": "Ren once identified a house in her sketch from its vanished shop sign.",
        "firsthand_memory": "Last autumn a visitor recognized their childhood street in her unfinished drawing.",
    },
    "Ren": {
        "background": "A volunteer cataloguer who learned the old street names delivering parcels.",
        "tension": "A good story makes the maps useful; an attractive but wrong label can mislead readers for years.",
        "relationship": "Mo has corrected two place names by remembering where the stream used to run.",
        "firsthand_memory": "Two maps labelled East Bank turned out to describe opposite banks in different years.",
    },
    "Mo": {
        "background": "A kitchen gardener keeping cuttings from neighbours who have moved away.",
        "tension": "Mo likes trading practical knowledge, but a visitor once took the last cutting of a rare herb.",
        "relationship": "Lina's pencil labels survived the rain when the ink labels washed off.",
        "firsthand_memory": "Last winter the shaded bed retained moisture longer than the sunny bed.",
    },
}
SCENES = {
    "studio": "The north window overlooks rooflines. Easels share space with a bench where visitors can sit.",
    "archive": "A table holds maps from several decades. Disputed labels are marked in pencil.",
    "garden": "Herb beds run beside a former stream. Slate markers identify plants donated by neighbours.",
}
LOCAL_CUES = {
    "studio": (
        "Light falls across the easel.",
        "The roofline is backlit.",
        "The bench lies in shade.",
    ),
    "archive": (
        "Street labels are easy to read.",
        "Glare crosses the map table.",
        "The east shelf is in shade.",
    ),
    "garden": ("Dew clings to the markers.", "The sunny bed is warm.", "Shadows reach the path."),
}


def surroundings(place, tick):
    return {
        "description": SCENES.get(place, "A place named during this trajectory."),
        "visible_now": LOCAL_CUES.get(place, ("", "", ""))[(tick // 4) % 3],
    }


def bounded_messages(instruction, view, limit):
    """UTF-8 bytes conservatively bound byte-tokenized text; reserve space for chat framing."""
    history = view.get("witnessed_events", [])
    base = {**view, "witnessed_events": []}
    remaining = limit - 128 - len(instruction.encode()) - len(json.dumps(base).encode())
    if remaining < 0:
        raise ValueError("Current decision context exceeds the input budget")
    kept = []
    for observation in reversed(history):
        cost = len(json.dumps(observation).encode()) + 2
        if cost > remaining:
            break
        kept.append(observation)
        remaining -= cost
    base["witnessed_events"] = kept[::-1]
    return [
        {"role": "system", "content": instruction},
        {"role": "user", "content": json.dumps(base)},
    ]
