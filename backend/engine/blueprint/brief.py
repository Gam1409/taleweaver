"""Open-ended world brief: established context and sources, without a prescribed outcome."""

import ipaddress
from typing import Literal
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BRIEF_KEY = "world_brief"
SOURCES_KEY = "world_brief_sources"


def public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        # Do not permit transition mechanisms to encode a private IPv4 destination.
        if address in ipaddress.ip_network("64:ff9b::/96") or address in ipaddress.ip_network(
            "64:ff9b:1::/48"
        ):
            return False
        mapped = address.ipv4_mapped or address.sixtofour
        if mapped is not None:
            return public_address(mapped)
    return True


def normalize_reference_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if any(ord(char) < 33 for char in value):
        raise ValueError("Reference URL must not contain whitespace or control characters.")
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Reference URL must be an http(s) page.")
    if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
        raise ValueError("Reference URLs cannot contain credentials or use custom ports.")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"localhost", "metadata.google.internal"} or hostname.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise ValueError("References must be public web pages.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not public_address(address):
        raise ValueError("References must be public web pages.")
    hostname = hostname.encode("idna").decode("ascii")
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="=&;%:@/?+,!$'()*~-._")
    return urlunsplit((parsed.scheme, netloc, path, query, ""))


class WorldReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(default="", max_length=2048)
    excerpt: str = Field(default="", max_length=3000)
    note: str = Field(default="", max_length=300)

    _url = field_validator("url")(normalize_reference_url)

    @model_validator(mode="after")
    def supplied_source(self) -> "WorldReference":
        if not self.url and not self.excerpt:
            raise ValueError("Provide a reference URL or a pasted source excerpt.")
        return self


class WorldBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    setting: str = Field(default="", max_length=2000)
    history: str = Field(default="", max_length=5000)
    opening: str = Field(default="", max_length=2000)
    world_rules: str = Field(default="", max_length=2000)
    characters: str = Field(default="", max_length=3000)
    open_threads: str = Field(default="", max_length=2000)
    references: list[WorldReference] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def bounded_brief(self) -> "WorldBrief":
        text = (
            self.setting,
            self.history,
            self.opening,
            self.world_rules,
            self.characters,
            self.open_threads,
        )
        if sum(map(len, text)) > 12000:
            raise ValueError(
                "The world brief may contain at most 12,000 characters, excluding sources."
            )
        urls = [ref.url for ref in self.references if ref.url]
        if len(set(urls)) != len(urls):
            raise ValueError("Each reference URL should appear only once.")
        return self


class SourceExcerpt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(default="", max_length=2048)
    resolved_url: str = Field(default="", max_length=2048)
    excerpt: str = Field(min_length=1, max_length=3000)
    kind: Literal["web", "author_excerpt"]
    note: str = Field(default="", max_length=300)


class SourceExcerpts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    entries: list[SourceExcerpt] = Field(max_length=3)
