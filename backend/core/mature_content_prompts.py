"""Optional mature-theme additions; existing narrative and image contracts remain in force.

Narration uses the saved VN adult-content setting. Image adaptation uses the
selected image profile's mature_themes setting. Restart the backend after edits.
These instructions supplement rather than replace the base prompts.
"""

NARRATIVE_ADDENDUM = (
    "MATURE THEMES — NARRATIVE ADDITION:\n"
    "When consistent with the established story, allow romantic tension, flirting and "
    "implied intimacy between clearly adult characters. Preserve each character's agency, "
    "boundaries and established relationship; do not force attraction or escalation. "
    "Keep intimate moments non-graphic and use a fade to black when appropriate. "
    "Do not sexualize minors or age-ambiguous characters. "
    "Keep the session language, narration format, pacing and engine-approved facts. "
    "This addition does not authorize changes to clothing, inventory, time or location."
)

IMAGE_PROMPT_ADDENDUM = (
    "When consistent with the supplied scene, allow romantic tension, flirting and implied "
    "intimacy between clearly adult characters. Do not add sexual context on your own. "
    "Do not describe sexual acts, intimate anatomy or graphic sexual details. "
    "Do not sexualize minors or age-ambiguous characters."
)
