"""Bounded narration samples; quotations and delivery cues are not narrator habits."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import islice

from backend.core.voice_repetition import strip_historical_voice_cues
from backend.core.voice_tags import VOICE_TAG_SET

MAX_REPLIES = 8
MAX_REPLY_CHARS = 2000
MAX_INPUT_CHARS = MAX_REPLIES * MAX_REPLY_CHARS
MAX_REPLY_TOKENS = 320
MAX_TOKENS = MAX_REPLIES * MAX_REPLY_TOKENS

_CJK = "\\u3400-\\u9fff\\u3040-\\u30ff\\uac00-\\ud7af\\U00020000-\\U0002ffff"
_TOKEN = re.compile(rf"[{_CJK}]|[^\W\d_{_CJK}]+|\d+(?:[.,]\d+)*")
_ATTRIBUTION = re.compile(
    rf"(?m)^[^\n:：]{{1,{MAX_REPLY_CHARS}}}[:：]\s*(?:\*{{1,2}}|_{{1,2}})?\s*"
    r'(?:\[[^\]\n]{1,64}\]\s*)?(?=["“«「『])'
)
_QUOTES = re.compile(
    r'"(?:[^"\\]|\\.)*(?:"|$)|“[^”]*(?:”|$)|«[^»]*(?:»|$)|「[^」]*(?:」|$)|『[^』]*(?:』|$)|‘[^’]*(?:’|$)'
)
_SENTENCE = re.compile(r"\.+(?=\s|$)|[!?。！？؟۔]+|…+(?=\s|$)|\n+")
_TONE = re.compile(r"\[([^\]\n]{1,64})\]")
_ARABIC_MARKS = re.compile(r"[\u0610-\u061a\u0640\u064b-\u065f\u0670\u06d6-\u06ed]")
_ELLIPSIS = re.compile(r"\.{3,}|…+")
_DASH = re.compile(r"(?<!\d)[—–](?!\d)|(?<!\w)-(?!\w)")
_PRONOUNS = frozenset(
    ["i", "you", "he", "she", "it", "we", "they", "я", "ты", "он", "она", "оно", "мы", "вы", "они"]
)
_FUNCTION_WORDS = frozenset(
    [
        "with",
        "from",
        "into",
        "over",
        "under",
        "this",
        "that",
        "these",
        "those",
        "there",
        "their",
        "them",
        "your",
        "yours",
        "our",
        "ours",
        "have",
        "has",
        "had",
        "were",
        "was",
        "been",
        "being",
        "would",
        "could",
        "should",
        "will",
        "when",
        "then",
        "while",
        "which",
        "very",
        "just",
        "still",
        "each",
        "both",
        "more",
        "only",
        "again",
        "after",
        "before",
        "through",
        "between",
        "этого",
        "этому",
        "этим",
        "это",
        "эти",
        "этот",
        "этой",
        "свои",
        "своей",
        "свою",
        "своих",
        "когда",
        "потом",
        "затем",
        "было",
        "были",
        "была",
        "будет",
        "быть",
        "очень",
        "снова",
        "еще",
        "ещё",
        "только",
        "того",
        "который",
        "которая",
        "которые",
        "которое",
        "перед",
        "после",
        "через",
        "между",
        "среди",
        "пока",
        "словно",
        "будто",
        "него",
        "сама",
        "هذا",
        "هذه",
        "ذلك",
        "تلك",
        "بعد",
        "قبل",
        "كانت",
        "كان",
        "إلى",
        "على",
        "في",
        "من",
        "عن",
        "مع",
        "وهي",
        "وهو",
        "ثم",
        "بين",
        "عندما",
        "التي",
        "الذي",
    ]
)
_ACTION_FORM = re.compile(r"[a-z]{3,}(?:ed|ing)|[а-яё]{3,}(?:ла|ли|ло|л)|[\u0600-\u06ff]{3,}ت")
_GESTURES = {
    "nod": re.compile(
        r"\b(?:nods?|nodded|nodding|кив\w*|[أا]وم[أا]\w*)\b|点头|點頭|うなず|頷|끄덕"
    ),
    "smile": re.compile(r"\b(?:smiles?|smiled|smiling|улыб\w*|ابتسم\w*)\b|微笑|ほほえ|微笑|미소"),
    "glance": re.compile(
        r"\b(?:glances?|glanced|glancing|взгляд\w*|огля\w*|نظر\w*)\b|瞥|目を向|시선"
    ),
    "sigh": re.compile(r"\b(?:sighs?|sighed|sighing|вздох\w*|تنهد\w*)\b|叹气|嘆氣|ため息|한숨"),
}


@dataclass(frozen=True)
class ReplySample:
    characters: int
    reply_characters: int
    tokens: int
    truncated: bool
    phrases: frozenset[tuple[str, ...]]
    openings: frozenset[tuple[str, ...]]
    closing: tuple[str, ...]
    gestures: frozenset[str]
    ellipses: int
    dashes: int
    question_closing: bool
    sentences: int


def samples(texts: Sequence[str]) -> tuple[tuple[ReplySample, ...], bool]:
    rows = []
    truncated = False
    for index in range(max(0, len(texts) - MAX_REPLIES), len(texts)):
        row, clipped = _sample(texts[index])
        truncated |= clipped
        if row is not None:
            rows.append(row)
    return tuple(rows), truncated


def _sample(text: str) -> tuple[ReplySample | None, bool]:
    prefix = text[:MAX_REPLY_CHARS]
    prose = _prose(prefix)
    truncated = len(text) > MAX_REPLY_CHARS or len(prose) > MAX_REPLY_CHARS
    prose = prose[:MAX_REPLY_CHARS]
    matches = list(islice(_TOKEN.finditer(prose), MAX_REPLY_TOKENS + 1))
    if len(matches) > MAX_REPLY_TOKENS:
        prose = prose[: matches[MAX_REPLY_TOKENS].start()].rstrip()
        matches = matches[:MAX_REPLY_TOKENS]
        truncated = True
    tokens = tuple(_word(match[0]) for match in matches)
    if not any(tokens):
        return None, truncated
    width = 8 if sum(_is_cjk(word) for word in tokens) > len(tokens) / 2 else 4
    sentences = [part for part in _SENTENCE.split(prose) if any(_words(part))]
    opening_width = 6 if width == 8 else 3
    openings = _openings(sentences, opening_width)
    closing = () if truncated or not sentences else _suffix(_words(sentences[-1]), opening_width)
    return ReplySample(
        len(prose),
        len(text),
        len(tokens),
        truncated,
        _sentence_phrases(sentences, width),
        openings,
        closing,
        frozenset(key for key, pattern in _GESTURES.items() if pattern.search(prose)),
        len(_ELLIPSIS.findall(prose)),
        len(_DASH.findall(prose)),
        not truncated and prose.rstrip().endswith(("?", "؟", "？")),
        len(sentences),
    ), truncated


def _prose(text: str) -> str:
    text = strip_historical_voice_cues(text)
    text = _TONE.sub(lambda match: " " if match[1].casefold() in VOICE_TAG_SET else match[0], text)
    text = _ATTRIBUTION.sub(" ", text)
    text = _QUOTES.sub(lambda match: "\n" * (match[0].count("\n") + 1), text)
    text = re.sub(r"(?m)^\s*>[^\n]*", " ", text)
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\S\n]+", " ", _ARABIC_MARKS.sub("", text)).strip()


def _word(value: str) -> str:
    return "" if any(char.isdigit() for char in value) else value


def _words(text: str) -> tuple[str, ...]:
    return tuple(_word(match[0]) for match in _TOKEN.finditer(text))


def _is_cjk(word: str) -> bool:
    return len(word) == 1 and bool(re.fullmatch(rf"[{_CJK}]", word))


def _grams(tokens: tuple[str, ...], width: int) -> frozenset[tuple[str, ...]]:
    return frozenset(
        part
        for index in range(max(0, len(tokens) - width + 1))
        if all(part := tokens[index : index + width])
    )


def _sentence_phrases(sentences: list[str], width: int) -> frozenset[tuple[str, ...]]:
    return frozenset(gram for sentence in sentences for gram in _phrases(_words(sentence), width))


def _phrases(tokens: tuple[str, ...], width: int) -> frozenset[tuple[str, ...]]:
    result = _grams(tokens, width)
    if width == 8:
        return result
    short = frozenset(
        gram
        for size in (2, 3)
        for gram in _grams(tokens, size)
        if _ACTION_FORM.fullmatch(gram[0]) and _salient(gram[0]) and _salient(gram[-1])
    )
    return result | short


def _salient(word: str) -> bool:
    return len(word) >= 4 and word not in _FUNCTION_WORDS


def _openings(sentences: list[str], width: int) -> frozenset[tuple[str, ...]]:
    starts = [_words(sentence) for sentence in sentences]
    longer = {_prefix(tokens, width) for tokens in starts}
    pronouns = {tokens[:1] for tokens in starts if tokens and tokens[0] in _PRONOUNS}
    return frozenset(value for value in longer | pronouns if value)


def _prefix(tokens: tuple[str, ...], width: int) -> tuple[str, ...]:
    return tokens[:width] if len(tokens) >= width and all(tokens[:width]) else ()


def _suffix(tokens: tuple[str, ...], width: int) -> tuple[str, ...]:
    return tokens[-width:] if len(tokens) >= width and all(tokens[-width:]) else ()
