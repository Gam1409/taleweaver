"""Structural coverage checks for the required explicit-atom subset.

This module is a check, not a prompt: it never rewrites NSFW prompt content,
policy addenda or the mature-content vocabulary. It verifies that explicit acts
grounded by scene staging survive into the final English image prompt, and it
reports missing acts or participants so the bounded retry can correct them.

The keyword table is output-format vocabulary for the English prompt surface,
not session-language data. Session-language evidence is never compared against
the prompt. Refinements bump :data:`VERSION` so recorded results stay
auditable.
"""

import re
from typing import Any

from backend.core.visual_trace import record

VERSION = 3

# CJK runs carry no alphabetic word-continuation (see also the quest guardrails):
# a name embedded inside such a run keeps substring semantics there, while
# alphabetic scripts require whole-name boundaries below.
_CJK_RE = re.compile(
    "[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]"
)

# Safe prefixes (leading word boundary only): innocent English words do not
# start with these strings (penetrat-, kiss-, undress-, masturbat-, ...).
_PREFIX_STEMS: dict[str, tuple[str, ...]] = {
    "kissing": ("kiss",),
    "undressing": ("undress", "strip"),
    "exposure": ("expos",),
    "manual": ("handjob", "fingering", "hand job"),
    "oral": ("blowjob", "fellatio", "cunnilingus", "deepthroat", "suck"),
    "vaginal": ("penetrat", "intercourse"),
    "anal": (),
    "masturbation": ("masturbat",),
    "grinding": (),
}

# Exact words only: short stems with innocent extensions ("analysis", "cocktail").
_EXACT_WORDS: dict[str, tuple[str, ...]] = {
    "anal": ("anal",),
    "grinding": ("grinding", "grinds"),
    "vaginal": ("vaginal", "sex", "pussy", "cunt", "cock", "dick", "cum"),
    "oral": ("oral",),
    "manual": (),
    "undressing": ("naked", "nude", "topless", "bottomless"),
    "kissing": (),
    "masturbation": (),
    "exposure": (
        "spread",
        "spreads",
        "spreading",
        "labia",
        "vulva",
        "uncovered",
        "displaying",
        "presenting",
    ),
}


def _folded(body: str) -> str:
    return " ".join(body.casefold().split())


def _is_cjk(char: str) -> bool:
    return bool(char and _CJK_RE.match(char))


def _blocks_name(char: str, name_is_cjk: bool) -> bool:
    """True when the neighbour continues the name into a longer word."""
    if not char:
        return False
    if char.isalnum() or char == "_":
        return not (name_is_cjk and _is_cjk(char))
    return False


def _mentions(name: str, folded: str) -> bool:
    """Whole-name boundary match: 'ann' must not be satisfied by 'anna'."""
    if not name:
        return False
    name_is_cjk = _is_cjk(name[0])
    for match in re.finditer(re.escape(name), folded):
        start, end = match.span()
        before = folded[start - 1] if start else ""
        after = folded[end] if end < len(folded) else ""
        if not _blocks_name(before, name_is_cjk) and not _blocks_name(after, name_is_cjk):
            return True
    return False


def _covered(folded: str, category: str) -> bool:
    for stem in _PREFIX_STEMS.get(category, ()):
        if re.search(rf"\b{re.escape(stem)}", folded):
            return True
    for word in _EXACT_WORDS.get(category, ()):
        if re.search(rf"\b{re.escape(word)}\b", folded):
            return True
    return False


def category_covered(body: str, category: str) -> bool:
    return _covered(_folded(body), category)


def _name_map(characters: Any) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for person in characters or ():
        if isinstance(person, dict):
            pid = str(person.get("id") or "")
            if pid:
                mapping[pid] = str(person.get("name") or pid)
    return mapping


def requirements(atoms: list[dict], characters: Any = ()) -> str:
    """Fidelity clause for the policy instructions; additive check feedback only."""
    if not atoms:
        return ""
    names = _name_map(characters)
    acts = []
    for atom in atoms:
        participants = ", ".join(
            names.get(str(pid), str(pid)) for pid in atom.get("participants") or []
        )
        acts.append(f"{atom.get('category')} between {participants}")
    return (
        "\nExplicit content fidelity contract: the saved scene establishes these explicit "
        "acts at the final instant: "
        + "; ".join(acts)
        + ". Depict every one of them explicitly and directly; do not soften, fade out, "
        "imply, or replace any act with milder contact or a metaphor. Include each act's "
        "stated visible anatomical state (exposed or spread anatomy, arousal, fluids, worn "
        "or removed clothing) in explicit English terms; residue of a past act is depicted "
        "as body state, never as a new active act. Use the participants' "
        "names verbatim as written; names are proper nouns and are never translated. "
        "These describe the image, never lettering or captions."
    )


def differences(body: str, atoms: list[dict], characters: Any = ()) -> list[str]:
    """Missing required explicit facts; empty means the subset is covered."""
    if not atoms:
        return []
    folded = _folded(body)
    names = _name_map(characters)
    missing: list[str] = []
    for atom in atoms:
        category = str(atom.get("category") or "")
        if category not in _PREFIX_STEMS and category not in _EXACT_WORDS:
            missing.append(f"Unknown explicit act category: {category}.")
            continue
        if not _covered(folded, category):
            missing.append(f"Preserve the explicit {category} act.")
            continue
        for participant in atom.get("participants") or []:
            label = names.get(str(participant), str(participant))
            name = " ".join(label.casefold().split())
            if not _mentions(name, folded):
                missing.append(f"Preserve {label} as an explicit act participant.")
    record("nsfw_guard.differences", missing=missing, version=VERSION)
    return missing


def status(mode: str, atoms: list[dict], missing: list[str]) -> dict:
    return {
        "mode": mode,
        "status": "not_run" if not atoms else ("passed" if not missing else "failed"),
        "checked": len(atoms),
        "missing": missing,
        "version": VERSION,
    }


def explicit_atoms(facts: Any) -> list[dict]:
    """Sanitized atom list from frozen snapshot facts; never trusts deeper shapes."""
    if not isinstance(facts, dict):
        return []
    atoms = facts.get("explicit")
    if not isinstance(atoms, list):
        return []
    return [atom for atom in atoms if isinstance(atom, dict) and atom.get("category")]
