"""Bounded read-only web references; no scripts, authentication, crawling or model calls."""

import asyncio
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpcore

from backend.engine.blueprint.brief import normalize_reference_url
from backend.engine.blueprint.reference_network import PublicReferenceBackend

MAX_PAGE_BYTES = 512_000
MAX_EXCERPT = 3000
MAX_REDIRECTS = 3
_IGNORED = {"script", "style", "noscript", "svg", "nav", "footer", "header", "template"}


class ReferenceText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ignored: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _IGNORED:
            self.ignored.append(tag)
        if tag in {"p", "li", "br", "h1", "h2", "h3", "article"} and not self.ignored:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.ignored:
            self.ignored = self.ignored[: self.ignored.index(tag)]

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)


def extract_reference_text(content: bytes, content_type: str) -> str:
    text = content.decode("utf-8", errors="replace")
    if "html" in content_type:
        parser = ReferenceText()
        parser.feed(text)
        text = " ".join(parser.parts)
    return " ".join(text.split())[:MAX_EXCERPT]


async def _read_page(response: httpcore.Response) -> dict[str, str]:
    headers = {key.lower(): value for key, value in response.headers}
    if response.status in {301, 302, 303, 307, 308}:
        location = headers.get(b"location", b"").decode("utf-8")
        if not location:
            raise ValueError("Reference redirect has no destination.")
        return {"redirect": location}
    if response.status != 200:
        raise ValueError(f"Reference page returned HTTP {response.status}.")
    content_type = headers.get(b"content-type", b"").decode("ascii", errors="replace").lower()
    if not content_type.startswith(("text/html", "text/plain", "application/xhtml+xml")):
        raise ValueError("Reference must be an HTML or plain-text page.")
    if headers.get(b"content-encoding", b"identity").lower() not in {b"identity", b""}:
        raise ValueError("Reference ignored the uncompressed response request.")
    data = bytearray()
    async for chunk in response.aiter_stream():
        data.extend(chunk[: MAX_PAGE_BYTES - len(data)])
        if len(data) >= MAX_PAGE_BYTES:
            break
    excerpt = extract_reference_text(bytes(data), content_type)
    if not excerpt:
        raise ValueError("Reference page contains no readable text.")
    return {"excerpt": excerpt, "kind": "web"}


async def _read_url(pool: httpcore.AsyncConnectionPool, url: str) -> dict[str, str]:
    headers = [
        ("User-Agent", "TaleWeaver reference-reader"),
        ("Accept", "text/html,text/plain"),
        ("Accept-Encoding", "identity"),
    ]
    extensions = {"timeout": {"connect": 5, "read": 5, "write": 5, "pool": 5}}
    async with pool.stream("GET", url, headers=headers, extensions=extensions) as response:
        return await _read_page(response)


async def _follow(pool: httpcore.AsyncConnectionPool, url: str) -> dict[str, str]:
    current = normalize_reference_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        result = await _read_url(pool, current)
        if "redirect" in result:
            current = normalize_reference_url(urljoin(current, result["redirect"]))
            continue
        return {"url": url, "resolved_url": current, **result}
    raise ValueError("Reference has too many redirects.")


async def _fetch(url: str) -> dict[str, str]:
    async with httpcore.AsyncConnectionPool(
        network_backend=PublicReferenceBackend(), max_connections=1, retries=0
    ) as pool:
        return await _follow(pool, url)


async def fetch_reference(url: str) -> dict[str, str]:
    try:
        return await asyncio.wait_for(_fetch(url), timeout=12)
    except (
        httpcore.NetworkError,
        httpcore.ProtocolError,
        httpcore.TimeoutException,
        TimeoutError,
    ) as exc:
        raise ValueError(
            "Reference could not be loaded. Paste its relevant excerpt or try another public page."
        ) from exc
