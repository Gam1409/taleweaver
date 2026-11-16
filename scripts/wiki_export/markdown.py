"""Rewrite local documentation links without executing or fetching their targets."""

import html
import posixpath
import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

DESTINATION = r"""(?:<[^>\n]+>|(?:\\.|[^\s()])+(?:\([^()\n]*\)[^\s()]*)*)"""
INLINE = re.compile(
    rf"""(!?\[[^\]\n]*\]\(\s*)({DESTINATION})((?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*\))"""
)
REFERENCE = re.compile(rf"^(\s{{0,3}}\[[^\]]+\]:\s*)({DESTINATION})(.*)$")
ATTRIBUTE = re.compile(r"""(\b(href|src)\s*=\s*)(["'])(.*?)\3""", re.IGNORECASE)


def _mask_code(line: str) -> tuple[str, dict[str, str]]:
    protected = {}
    prefix = "\x00wiki-code-"
    while prefix in line:
        prefix += "-"

    def replace(match: re.Match) -> str:
        key = prefix + str(len(protected)) + "\x00"
        protected[key] = match[0]
        return key

    return re.sub(r"(`+)(.*?)\1", replace, line), protected


def _restore(line: str, protected: dict[str, str]) -> str:
    for key, value in protected.items():
        line = line.replace(key, value)
    return line


def _label(value: str) -> str:
    return " ".join(value.split()).casefold()


def _image_references(text: str) -> set[str]:
    labels, fence = set(), None
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            fence = (
                token
                if fence is None
                else None
                if token[0] == fence[0] and len(token) >= len(fence)
                else fence
            )
            continue
        if fence is not None:
            continue
        masked, protected = _mask_code(line)
        labels.update(
            _label(_restore(match[2] or match[1], protected))
            for match in re.finditer(r"!\[([^\]]*)\](?:\[([^\]]*)\])?(?!\()", masked)
        )
    return labels


def _destination(
    target: str,
    current: str,
    pages: dict[str, str],
    tree: dict,
    source: str,
    revision: str,
    *,
    image: bool = False,
) -> str:
    wrapped = target.startswith("<") and target.endswith(">")
    original = target[1:-1] if wrapped else target
    value = re.sub(r"\\([\s()])", r"\1", original)
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return target
    decoded = unquote(parsed.path, errors="strict")
    path = posixpath.normpath(
        decoded.lstrip("/")
        if decoded.startswith("/")
        else posixpath.join(posixpath.dirname(current), decoded)
    )
    if path.startswith("../") or path == "..":
        raise ValueError(f"Documentation link leaves the repository in {current}.")
    directory = any(name.startswith(path.rstrip("/") + "/") for name in tree)
    if directory and path + "/README.md" in pages:
        path = path + "/README.md"
    if path in pages and not image:
        destination = quote(pages[path], safe="-._")
    elif path in tree or directory:
        base = (
            source.replace("https://github.com/", "https://raw.githubusercontent.com/")
            if image
            else source
        )
        kind = "" if image else "tree/" if directory else "blob/"
        destination = f"{base}/{kind}{revision}/{quote(path, safe='/')}"
    elif decoded.startswith("/"):
        return target
    else:
        raise ValueError(f"Missing source link in {current}: {decoded}")
    destination = urlunsplit(("", "", destination, parsed.query, parsed.fragment))
    return "<" + destination + ">" if wrapped else destination


def rewrite(
    text: str, current: str, pages: dict[str, str], tree: dict, source: str, revision: str
) -> str:
    images = _image_references(text)

    def destination(value: str, image: bool = False) -> str:
        return _destination(value, current, pages, tree, source, revision, image=image)

    def inline(match: re.Match) -> str:
        return match[1] + destination(match[2], match[1].startswith("!")) + match[3]

    def attribute(match: re.Match) -> str:
        value = html.unescape(match[4])
        rewritten = destination(value, match[2].lower() == "src")
        return (
            match[0]
            if rewritten == value
            else match[1] + match[3] + html.escape(rewritten, quote=True) + match[3]
        )

    lines, fence = [], None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            fence = (
                token
                if fence is None
                else None
                if token[0] == fence[0] and len(token) >= len(fence)
                else fence
            )
            lines.append(line)
            continue
        if fence is not None:
            lines.append(line)
            continue
        masked, protected = _mask_code(line)
        reference = REFERENCE.match(masked)
        if reference:
            label = re.search(r"\[([^\]]+)\]", reference[1])
            is_image = label is not None and _label(_restore(label[1], protected)) in images
            lines.append(
                _restore(
                    reference[1]
                    + destination(reference[2], is_image)
                    + reference[3]
                    + ("\n" if line.endswith("\n") else ""),
                    protected,
                )
            )
            continue
        lines.append(_restore(ATTRIBUTE.sub(attribute, INLINE.sub(inline, masked)), protected))
    return "".join(lines)
