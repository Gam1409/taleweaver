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
import unicodedata
from typing import Any

from backend.core.visual_trace import record

VERSION = 4

# Latin romanization tolerance for participant names. The verbatim name stays
# the primary contract; one consistent Latin form must also satisfy the check,
# because adapters routinely romanize non-Latin proper nouns while writing the
# English prompt surface. Tables are deterministic and dependency-free and
# cover scripts with a standard Latin form: Cyrillic, Greek, kana (Hepburn
# style) and Hangul (Revised style), plus Latin diacritics. Han ideographs and
# abjad scripts (Arabic, Hebrew, Thai, ...) have no dependable table: their
# names stay verbatim-only and the bounded retry repeats the exact name.
_CHAR_UNITS: dict[str, tuple[str, ...]] = {
    # Cyrillic (multi-letter Russian pairs first; includes Ukrainian/Belarusian
    # and Serbian extensions).
    "щ": ("shch", "sch"),
    "ж": ("zh", "j"),
    "х": ("kh", "h"),
    "ц": ("ts", "c"),
    "ё": ("yo", "e"),
    "ю": ("yu", "iu"),
    "я": ("ya", "ia"),
    "й": ("y", "i", ""),
    "ы": ("y", "i"),
    "і": ("i",),
    "ї": ("yi", "ji"),
    "є": ("ye", "je"),
    "ґ": ("g",),
    "ў": ("u", "w"),
    "љ": ("lj",),
    "њ": ("nj",),
    "џ": ("dz",),
    "ћ": ("c", "ch"),
    "ђ": ("dj",),
    "а": ("a",),
    "б": ("b",),
    "в": ("v",),
    "г": ("g",),
    "д": ("d",),
    "е": ("e",),
    "з": ("z",),
    "и": ("i",),
    "к": ("k",),
    "л": ("l",),
    "м": ("m",),
    "н": ("n",),
    "о": ("o",),
    "п": ("p",),
    "р": ("r",),
    "с": ("s",),
    "т": ("t",),
    "у": ("u",),
    "ф": ("f",),
    "э": ("e",),
    "ь": ("",),
    "ъ": ("",),
    # Greek (monotonic; accents fold away before the scan).
    "α": ("a",),
    "β": ("v", "b"),
    "γ": ("g",),
    "δ": ("d",),
    "ε": ("e",),
    "ζ": ("z",),
    "η": ("i",),
    "θ": ("th",),
    "ι": ("i",),
    "κ": ("k",),
    "λ": ("l",),
    "μ": ("m",),
    "ν": ("n",),
    "ξ": ("x",),
    "ο": ("o",),
    "π": ("p",),
    "ρ": ("r",),
    "σ": ("s",),
    "ς": ("s",),
    "τ": ("t",),
    "υ": ("y", "i", "u"),
    "φ": ("f",),
    "χ": ("ch", "h"),
    "ψ": ("ps",),
    "ω": ("o",),
    # Latin letters without a combining decomposition.
    "ł": ("l",),
    "ø": ("o",),
    "đ": ("d",),
    "ð": ("d",),
    "þ": ("th",),
    "æ": ("ae",),
    "œ": ("oe",),
    "ß": ("ss",),
    # Kana (Hepburn style, macron-less; katakana mirrors are added below).
    "あ": ("a",),
    "い": ("i",),
    "う": ("u",),
    "え": ("e",),
    "お": ("o",),
    "か": ("ka",),
    "き": ("ki",),
    "く": ("ku",),
    "け": ("ke",),
    "こ": ("ko",),
    "が": ("ga",),
    "ぎ": ("gi",),
    "ぐ": ("gu",),
    "げ": ("ge",),
    "ご": ("go",),
    "さ": ("sa",),
    "し": ("shi",),
    "す": ("su",),
    "せ": ("se",),
    "そ": ("so",),
    "ざ": ("za",),
    "じ": ("ji",),
    "ず": ("zu",),
    "ぜ": ("ze",),
    "ぞ": ("zo",),
    "た": ("ta",),
    "ち": ("chi",),
    "つ": ("tsu",),
    "て": ("te",),
    "と": ("to",),
    "だ": ("da",),
    "ぢ": ("ji",),
    "づ": ("zu",),
    "で": ("de",),
    "ど": ("do",),
    "な": ("na",),
    "に": ("ni",),
    "ぬ": ("nu",),
    "ね": ("ne",),
    "の": ("no",),
    "は": ("ha",),
    "ひ": ("hi",),
    "ふ": ("fu",),
    "へ": ("he",),
    "ほ": ("ho",),
    "ば": ("ba",),
    "び": ("bi",),
    "ぶ": ("bu",),
    "べ": ("be",),
    "ぼ": ("bo",),
    "ぱ": ("pa",),
    "ぴ": ("pi",),
    "ぷ": ("pu",),
    "ぺ": ("pe",),
    "ぽ": ("po",),
    "ま": ("ma",),
    "み": ("mi",),
    "む": ("mu",),
    "め": ("me",),
    "も": ("mo",),
    "や": ("ya",),
    "ゆ": ("yu",),
    "よ": ("yo",),
    "ら": ("ra",),
    "り": ("ri",),
    "る": ("ru",),
    "れ": ("re",),
    "ろ": ("ro",),
    "わ": ("wa",),
    "ゐ": ("wi",),
    "ゑ": ("we",),
    "を": ("o",),
    "ん": ("n",),
    "っ": ("",),
    "ゃ": ("",),
    "ゅ": ("",),
    "ょ": ("",),
    "ぁ": ("",),
    "ぃ": ("",),
    "ぅ": ("",),
    "ぇ": ("",),
    "ぉ": ("",),
}


def _katakana_mirror(units: dict[str, tuple[str, ...]]) -> None:
    """Add katakana keys for hiragana keys (fixed Unicode offset)."""
    for key, value in list(units.items()):
        if all(0x3041 <= ord(char) <= 0x3096 for char in key):
            units["".join(chr(ord(char) + 0x60) for char in key)] = value


_katakana_mirror(_CHAR_UNITS)

# Multi-character units are checked before single characters.
_MULTI_UNITS: dict[str, tuple[str, ...]] = {
    "кс": ("ks", "x"),  # Cyrillic
    "ου": ("ou", "u"),
    "μπ": ("b",),
    "ντ": ("d",),
    "γκ": ("g",),
    "γγ": ("ng",),  # Greek
    "きゃ": ("kya",),
    "きゅ": ("kyu",),
    "きょ": ("kyo",),
    "しゃ": ("sha",),
    "しゅ": ("shu",),
    "しょ": ("sho",),
    "ちゃ": ("cha",),
    "ちゅ": ("chu",),
    "ちょ": ("cho",),
    "にゃ": ("nya",),
    "にゅ": ("nyu",),
    "にょ": ("nyo",),
    "ひゃ": ("hya",),
    "ひゅ": ("hyu",),
    "ひょ": ("hyo",),
    "みゃ": ("mya",),
    "みゅ": ("myu",),
    "みょ": ("myo",),
    "りゃ": ("rya",),
    "りゅ": ("ryu",),
    "りょ": ("ryo",),
    "ぎゃ": ("gya",),
    "ぎゅ": ("gyu",),
    "ぎょ": ("gyo",),
    "じゃ": ("ja",),
    "じゅ": ("ju",),
    "じょ": ("jo",),
    "びゃ": ("bya",),
    "びゅ": ("byu",),
    "びょ": ("byo",),
    "ぴゃ": ("pya",),
    "ぴゅ": ("pyu",),
    "ぴょ": ("pyo",),
    "ふぁ": ("fa",),
    "ふぃ": ("fi",),
    "ふぇ": ("fe",),
    "ふぉ": ("fo",),
}

_katakana_mirror(_MULTI_UNITS)

# Hangul syllables (U+AC00..): Revised Romanization without positional
# assimilation; final consonants use the unreleased-syllable forms.
_HANGUL_CHO = (
    "g",
    "kk",
    "n",
    "d",
    "tt",
    "r",
    "m",
    "b",
    "pp",
    "s",
    "ss",
    "",
    "j",
    "jj",
    "ch",
    "k",
    "t",
    "p",
    "h",
)
_HANGUL_JUNG = (
    "a",
    "ae",
    "ya",
    "yae",
    "eo",
    "e",
    "yeo",
    "ye",
    "o",
    "wa",
    "wae",
    "oe",
    "yo",
    "u",
    "wo",
    "we",
    "wi",
    "yu",
    "eu",
    "ui",
    "i",
)
_HANGUL_JONG = (
    "",
    "k",
    "k",
    "k",
    "n",
    "n",
    "n",
    "t",
    "l",
    "k",
    "m",
    "p",
    "l",
    "l",
    "p",
    "l",
    "m",
    "p",
    "p",
    "t",
    "t",
    "ng",
    "t",
    "t",
    "k",
    "t",
    "p",
    "t",
)
_MAX_ROMAN_VARIANTS = 16

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


def _is_han(char: str) -> bool:
    code = ord(char) if char else 0
    return 0x3400 <= code <= 0x4DBF or 0x4E00 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF


def _has_non_ascii_letters(value: str) -> bool:
    return any(char.isalpha() and ord(char) > 127 for char in value)


def _scan_char(char: str) -> str | None:
    """Reduce one character to a scannable form; None means unromanizable."""
    if char in _CHAR_UNITS or char.isascii() or 0xAC00 <= ord(char) <= 0xD7A3:
        return char  # Hangul syllables are kept whole for the jamo scan.
    decomposed = unicodedata.normalize("NFKD", char)
    folded = "".join(part for part in decomposed if not unicodedata.combining(part))
    if folded and (folded.isascii() or all(part in _CHAR_UNITS for part in folded)):
        return folded
    return None


def _hangul_alternatives(char: str) -> tuple[str, ...]:
    code = ord(char) - 0xAC00
    cho, rest = divmod(code, 588)
    jung, jong = divmod(rest, 28)
    return (_HANGUL_CHO[cho] + _HANGUL_JUNG[jung] + _HANGUL_JONG[jong],)


def _roman_alternatives(word: str) -> tuple[str, ...] | None:
    """Plausible Latin spellings of one word; None when it cannot be romanized."""
    scanned: list[str | None] = [_scan_char(char) for char in word.casefold()]
    if any(part is None for part in scanned):
        return None
    low = "".join(part for part in scanned if part)
    variants = [""]
    index = 0
    while index < len(low):
        char = low[index]
        if _is_han(char):
            return None
        if 0xAC00 <= ord(char) <= 0xD7A3:
            additions, step = _hangul_alternatives(char), 1
        else:
            pair = low[index : index + 2]
            unit = pair if pair in _MULTI_UNITS else char
            if unit in _MULTI_UNITS:
                additions = _MULTI_UNITS[unit]
            elif char in _CHAR_UNITS:
                additions = _CHAR_UNITS[char]
                if char == "е" and index == 0:
                    additions = ("e", "ye")
            elif char.isalnum():
                additions = (char,)
            else:
                # Punctuation inside a name is kept literally (e.g. "Dr.").
                additions = (re.escape(char),)
            step = len(unit)
        variants = [prefix + addition for prefix in variants for addition in additions]
        if len(variants) > _MAX_ROMAN_VARIANTS:
            return None
        index += step
    return tuple(dict.fromkeys(variants))


def _romanized_pattern(label: str) -> str | None:
    """\\b-anchored regex matching consistent romanizations of the whole label."""
    parts: list[str] = []
    romanized = False
    for word in label.split():
        alternatives = _roman_alternatives(word)
        if alternatives is None:
            return None
        if _has_non_ascii_letters(word):
            romanized = True
        parts.append(
            alternatives[0] if len(alternatives) == 1 else "(?:" + "|".join(alternatives) + ")"
        )
    if not romanized:
        return None
    return r"\b" + r"\s+".join(parts) + r"\b"


def _mentions_label(label: str, folded: str) -> bool:
    """Verbatim whole-name match, else one consistent Latin romanization."""
    name = " ".join(label.casefold().split())
    if _mentions(name, folded):
        return True
    pattern = _romanized_pattern(name)
    return bool(pattern and re.search(pattern, folded))


def _participant_mentioned(label: str, folded: str) -> bool:
    """Presence of an act participant in the English prompt body.

    ASCII-Latin labels keep the strict whole-name semantics. Labels written in
    any other script also accept a consistent Latin romanization, and for
    multi-word labels the given name (the final word) alone, because adapters
    routinely translate a title ('Доктор Рин' -> 'Doctor Rin') while
    romanizing the proper noun.
    """
    if _mentions_label(label, folded):
        return True
    if _has_non_ascii_letters(label):
        words = label.split()
        if len(words) > 1:
            return _mentions_label(words[-1], folded)
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
        "names verbatim as written; a consistent Latin romanization of a non-Latin "
        "name is equally valid, but names are proper nouns and are never translated "
        "or dropped. "
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
            if not _participant_mentioned(label, folded):
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
