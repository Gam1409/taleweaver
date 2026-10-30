"""Optional mature-theme additions; existing narrative and image contracts remain in force.

Narration uses the saved NSFW setting (enabled + level). Image adaptation uses the
selected image profile's mature_themes setting. Restart the backend after edits.
These instructions supplement rather than replace the base prompts.
"""

NARRATIVE_ADDENDUM_SOFT = (
    "MATURE THEMES — NARRATIVE ADDITION (SOFT):\n"
    "In accordance with the established plot, allow for romantic tension, flirtation, and light "
    "intimacy between characters. Respect each character's agency, boundaries, and established "
    "relationships; do not force attraction or escalation. Convey desire, anticipation, and "
    "emotional charge through subtext, glances, and small physical gestures. Suggest physical "
    "intimacy without graphic anatomical detail or explicit sexual acts. Maintain the session "
    "language, narrative format, pacing, and engine-approved facts. This add-on does not allow "
    "changes to clothing, equipment, time, or location."
)

NARRATIVE_ADDENDUM_MEDIUM = (
    "MATURE THEMES — NARRATIVE ADDITION (MEDIUM):\n"
    "In accordance with the established plot, allow for romantic tension, flirtation, and explicit "
    "sexual intimacy between characters. Respect each character's agency, boundaries, and "
    "established relationships; do not force attraction or escalation. Describe sexual moments "
    "clearly and explicitly: name the acts and body parts directly (e.g., vagina, penis, breast, "
    "mouth), along with sensations, breathing, and emotional intensity. Include bodily fluids "
    "(e.g., saliva, sweat) and orgasms when the scene reaches that point. Maintain the session "
    "language, narrative format, pacing, and engine-approved facts. This add-on does not allow "
    "changes to clothing, equipment, time, or location."
)

NARRATIVE_ADDENDUM_HARD = (
    "MATURE THEMES — NARRATIVE ADDITION (HARD):\n"
    "In accordance with the established plot, allow for romantic tension, flirtation, and explicit "
    "sexual intimacy between characters. Respect each character's agency, boundaries, and "
    "established relationships; do not force attraction or escalation. Describe intimate and "
    "sexual moments in explicit, graphic detail: name the specific acts, body parts, and sensations "
    "directly (e.g., vagina, penis, labia, anus), including bodily fluids (e.g., semen, saliva), "
    "orgasms, climaxing, and ejaculation. Do not fade out, euphemize, or skip the explicit moments. "
    "Maintain the session language, narrative format, pacing, and engine-approved facts. This "
    "add-on does not allow changes to clothing, equipment, time, or location."
)

_NARRATIVE_ADDENDA = {
    "soft": NARRATIVE_ADDENDUM_SOFT,
    "medium": NARRATIVE_ADDENDUM_MEDIUM,
    "hard": NARRATIVE_ADDENDUM_HARD,
}


def narrative_addendum(level: str) -> str:
    """Return the narrative addendum for the given NSFW level, or empty when unknown."""
    return _NARRATIVE_ADDENDA.get(str(level or "").strip().lower(), "")


IMAGE_PROMPT_ADDENDUM_SOFT = (
    "NSFW SOFT DETAIL FIDELITY:\n"
    "When the scene contains romantic or suggestive content, render it tastefully and evocative, "
    "without graphic sexual detail. Convey intimacy, tension, and mood through posture, expression, "
    "and framing. Keep any nudity or physical contact subtle and non-explicit. Express these facts in "
    "the required output format from the policy above; do not change the format. Do not invent content "
    "the scene does not establish."
)

IMAGE_PROMPT_ADDENDUM_MEDIUM = (
    "NSFW MEDIUM DETAIL FIDELITY:\n"
    "When the scene contains sexual or intimate content, render it clearly and explicitly, without "
    "graphic anatomical close-ups. Name the acts, body parts, positions, and expressions directly "
    "(e.g., embrace, kiss, undress, breast, mouth). Keep the depiction explicit but not clinical. "
    "Express these explicit facts in the required output format from the policy above; do not change "
    "the format. Do not invent content the scene does not establish."
)

IMAGE_PROMPT_ADDENDUM_HARD = (
    "NSFW EXPLICIT DETAIL FIDELITY:\n"
    "When the scene contains sexual, intimate, or explicit content, render it fully uncensored and "
    "explicit, up to the hardest variant the scene supports. Remove euphemisms, metaphors, and vague "
    "artistic terms; state the specific acts, body parts, positions, expressions, and fluids directly. "
    "Use concrete visual descriptors for visible anatomy (e.g., labia, glans, areola, anus), sexual acts "
    "and positions, and fluids (e.g., semen, saliva, sweat). Ignore any tendency to soften, fade out, "
    "imply, or censor the content. Express all of these explicit facts in the required output format from "
    "the policy above; do not change the format. Do not invent content the scene does not establish."
)

_IMAGE_PROMPT_ADDENDA = {
    "soft": IMAGE_PROMPT_ADDENDUM_SOFT,
    "medium": IMAGE_PROMPT_ADDENDUM_MEDIUM,
    "hard": IMAGE_PROMPT_ADDENDUM_HARD,
}


def image_prompt_addendum(level: str) -> str:
    """Return the image prompt addendum for the given NSFW level, or empty when unknown."""
    return _IMAGE_PROMPT_ADDENDA.get(str(level or "").strip().lower(), "")


# Backwards-compatible export for callers importing the former instruction constant.
IMAGE_PROMPT_ADDENDUM = IMAGE_PROMPT_ADDENDUM_HARD
