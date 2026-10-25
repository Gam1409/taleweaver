"""Visual-novel world setup without mandatory RPG progression."""

from typing import Any

from backend.core.game_modes import is_vn

VN_WORLD_SYSTEM_PROMPT = """You design the starting situation for an interactive visual novel.
Return the supplied structured world schema. Preserve its JSON keys, enums and ID references.
Build a premise, a small cast with distinct voices, believable places and unresolved interpersonal
threads. The player controls their own words, actions, commitments and emotional conclusions.
The selected tone and user premise govern the genre; a visual novel need not be romantic.

Write `plot` as the current situation, competing needs, possible tensions and open questions,
not a predetermined ending or a walkthrough. Write `rules` as setting and narrative constraints.
Use each character's existing `goal` for their present personal motivation and `character` for
stable values, boundaries, voice and temperament. Biography may contain history, private concerns,
relationships and knowledge, but do not make secrets automatically known to the protagonist.
Treat private belongings separately from what the player has observed. Relationships can include
friendship, rivalry, family and romance; they require context and agency, not an automatic score win.
Use `intro_text` for one playable opening moment with room for the player's response, not a recap
of a completed conversation. Do not decide the player's dialogue or force a confession or ending.

This mode has no mechanical combat, quests, XP, awards or mandatory linear chapter progression.
Set `quests`, `awards`, `sequences`, `scripts` to []; `init_script` to null.
Set both damage flags false. Leave win/loss conditions and guard expressions empty.
Do not invent puzzle gates, combat abilities, attack triggers, locked progression or XP rewards.
Keep required legacy character stats valid but neutral: they are unused compatibility fields.
NPC attack_mode must be PASSIVE and special_actions empty. Locations and exits must still use
consistent IDs; every referenced start_scene_id, item ID and exit endpoint must exist.
Ordinary meaningful possessions, letters and places are welcome without turning them into rewards.
Descriptions and dialogue are content; JSON keys, enums, IDs and references are technical data.
"""


def build_vn_world_prompts(
    *,
    title: str,
    original_prompt: str,
    language: str | None,
    selected_tone: str | None,
    scene_requirement: str,
    item_requirement: str,
    cover_guidance: str,
    sequences: list[dict[str, Any]] | None,
) -> tuple[str, str]:
    system = VN_WORLD_SYSTEM_PROMPT
    if language:
        system += (
            f"\nWrite all human-readable content in {language}. Keep schema keys, enums, "
            "technical identifiers and reference links unchanged."
        )
    outline = ""
    if sequences:
        beats = [f"{s.get('title', '')}: {s.get('description', '')}" for s in sequences]
        outline = (
            "\nUser outline (possible themes and situations, not mandatory ordered objectives):\n"
            + "\n".join(beats)
        )
    user = (
        f"Title: {title}\nPremise: {original_prompt}\nTone: {selected_tone or 'Natural and grounded'}\n"
        f"{scene_requirement}\n{item_requirement}\n{outline}\n{cover_guidance}\n"
        "Create a coherent starting cast and situation. Keep interpersonal threads in plot and "
        "character information, never in quests or mandatory sequences."
    )
    return system, user


def normalize_vn_generated_manifest(manifest: dict[str, Any]) -> None:
    """Enforce VN defaults even when the generator emits RPG schema defaults."""
    for field in ("quests", "awards", "sequences", "scripts"):
        manifest[field] = []
    for field in (
        "walkthrough",
        "completed_condition",
        "gameover_condition",
        "completed_guard_expression",
        "gameover_guard_expression",
    ):
        manifest[field] = ""
    manifest.update(
        rule_enforcement_mode="vn",
        strict_rules=False,
        can_damage_npcs=False,
        npcs_can_damage_protagonist=False,
        init_script=None,
    )
    protagonist = manifest.get("protagonist")
    if isinstance(protagonist, dict):
        protagonist["special_actions"] = []
    for character in manifest.get("npcs") or []:
        character["special_actions"] = []
        character["attack_mode"] = "PASSIVE"
        character["attack_trigger"] = None


def vn_editor_guidance(adventure: Any) -> str:
    """Keep validation and repair from treating intentional VN omissions as defects."""
    if not is_vn(adventure):
        return ""
    return (
        "\nVISUAL NOVEL MODE: Empty walkthrough, win/loss conditions, quests, awards, "
        "sequences and scripts are intentional, not missing content. Do not invent mechanical "
        "combat, XP, mandatory objectives, puzzle gates or forced romantic progression. "
        "Validate coherent places and ID references, cast motivations, stable values, "
        "knowledge boundaries, and an open playable premise. Preserve mode='vn' and disabled "
        "mechanics. Repair actual contradictions without prescribing the player's choices.\n"
    )
