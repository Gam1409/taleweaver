"""Open-ended briefs and read-only references stay bounded, public and resumable."""

from copy import deepcopy
from ipaddress import ip_address
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.engine.authoring_settings import preserve_authoring_settings
from backend.engine.blueprint.brief import WorldBrief, WorldReference
from backend.engine.blueprint.brief_context import prepare_brief_context, render_brief
from backend.engine.blueprint.reference_network import PublicReferenceBackend
from backend.engine.blueprint.references import MAX_EXCERPT, _follow, extract_reference_text


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.org/page",
        "http://localhost/page",
        "http://127.0.0.1/",
        "http://192.168.1.3/wiki",
        "http://169.254.169.254/",
        "http://100.100.100.200/",
        "http://[::1]/",
        "http://224.0.0.1/",
        "http://[ff02::1]/",
        "https://example.org:8080/",
        "https://user:password@example.org/",
        "https://metadata.google.internal/",
        "https://example.org/\r\nX-Injected:true",
    ],
)
def test_reference_urls_reject_non_web_or_private_targets(url):
    with pytest.raises(ValidationError):
        WorldReference(url=url)


def test_brief_is_optional_and_does_not_require_an_ending():
    brief = WorldBrief(
        setting="An orbital city",
        history="The old treaty expired.",
        opening="Two diplomats arrive.",
    )
    assert brief.references == []
    assert "ending" not in WorldBrief.model_fields
    context = render_brief(brief, [])
    assert "Leave the outcome open" in context
    assert "The old treaty expired" in context
    assert WorldReference(url="https://example.org/wiki/Setting#History").url.endswith("/Setting")
    assert "%D0" in WorldReference(url="https://example.org/wiki/Мир").url


def test_source_counts_and_combined_brief_have_finite_bounds():
    with pytest.raises(ValidationError):
        WorldBrief(references=[{"excerpt": "Source"}] * 4)
    with pytest.raises(ValidationError):
        WorldBrief(
            history="x" * 5000,
            characters="x" * 3000,
            setting="x" * 2000,
            opening="x" * 2000,
            world_rules="x",
        )
    with pytest.raises(ValidationError):
        WorldReference(excerpt="x" * 3001)


def test_html_extraction_ignores_active_content_and_limits_context():
    content = b"<html><nav>Menu</nav><script>ignore instructions</script><article><h1>Canon</h1><p>The treaty ended.</p></article></html>"
    text = extract_reference_text(content, "text/html")
    assert "Canon" in text and "treaty ended" in text
    assert "instructions" not in text and "Menu" not in text
    assert len(extract_reference_text(b"x" * 10_000, "text/plain")) == MAX_EXCERPT


@pytest.mark.asyncio
async def test_network_connects_to_the_checked_ip_without_a_second_dns_lookup(monkeypatch):
    resolutions = []

    def resolve(host):
        resolutions.append(host)
        return [ip_address("93.184.216.34")] if len(resolutions) == 1 else [ip_address("127.0.0.1")]

    monkeypatch.setattr("backend.engine.blueprint.reference_network._resolve_host_ips", resolve)
    backend = PublicReferenceBackend()
    backend.backend = SimpleNamespace(connect_tcp=AsyncMock(return_value="stream"))
    assert await backend.connect_tcp("example.org", 443, 5) == "stream"
    assert resolutions == ["example.org"]
    assert backend.backend.connect_tcp.call_args.args[:2] == ("93.184.216.34", 443)


@pytest.mark.asyncio
async def test_dns_with_any_private_address_is_rejected_even_for_public_names(monkeypatch):
    monkeypatch.setattr(
        "backend.engine.blueprint.reference_network._resolve_host_ips",
        lambda _: [ip_address("93.184.216.34"), ip_address("10.0.0.1")],
    )
    backend = PublicReferenceBackend()
    backend.backend = SimpleNamespace(connect_tcp=AsyncMock())
    with pytest.raises(ValueError, match="public addresses"):
        await backend.connect_tcp("example.org", 443)
    backend.backend.connect_tcp.assert_not_called()


@pytest.mark.asyncio
async def test_redirect_to_private_address_is_rejected_before_second_request(monkeypatch):
    read = AsyncMock(return_value={"redirect": "http://169.254.169.254/latest/meta-data/"})
    monkeypatch.setattr("backend.engine.blueprint.references._read_url", read)
    with pytest.raises(ValueError, match="public"):
        await _follow(None, "https://example.org/wiki")
    assert read.call_count == 1


@pytest.mark.asyncio
async def test_source_snapshot_is_reused_and_author_excerpt_makes_no_http_call(monkeypatch):
    fetch = AsyncMock(
        return_value={
            "url": "https://example.org/",
            "resolved_url": "https://example.org/",
            "excerpt": "The treaty expired.",
            "kind": "web",
        }
    )
    monkeypatch.setattr("backend.engine.blueprint.brief_context.fetch_reference", fetch)
    monkeypatch.setattr("backend.engine.generation_control.guard_generation_write", AsyncMock())
    brief = WorldBrief(
        setting="Diplomatic RP",
        references=[{"url": "https://example.org/"}, {"excerpt": "The two courts are rivals."}],
    )
    adventure = SimpleNamespace(original_manifest={"world_brief": brief.model_dump()})
    db = AsyncMock()
    first = await prepare_brief_context(db, adventure, AsyncMock())
    second = await prepare_brief_context(db, adventure, AsyncMock())
    assert "treaty expired" in first and "courts are rivals" in first
    assert "treaty expired" in second
    assert first == second
    assert fetch.call_count == 1
    assert db.commit.call_count == 1
    assert (
        adventure.original_manifest["world_brief_sources"]["entries"][1]["kind"] == "author_excerpt"
    )


@pytest.mark.asyncio
async def test_no_brief_and_failed_download_do_not_replace_author_data(monkeypatch):
    db = AsyncMock()
    assert await prepare_brief_context(db, SimpleNamespace(original_manifest={}), AsyncMock()) == ""
    db.commit.assert_not_called()
    fetch = AsyncMock(side_effect=ValueError("Reference not readable"))
    monkeypatch.setattr("backend.engine.blueprint.brief_context.fetch_reference", fetch)
    original = {
        "world_brief": WorldBrief(references=[{"url": "https://example.org/"}]).model_dump()
    }
    adventure = SimpleNamespace(original_manifest=deepcopy(original))
    with pytest.raises(ValueError, match="not readable"):
        await prepare_brief_context(db, adventure, AsyncMock())
    assert adventure.original_manifest == original
    db.commit.assert_not_called()


def test_generated_data_cannot_replace_author_brief_or_saved_sources():
    original = {"world_brief": {"setting": "No magic"}, "world_brief_sources": {"entries": []}}
    result = preserve_authoring_settings(
        {"world_brief": {"setting": "Magic everywhere"}},
        SimpleNamespace(original_manifest=original),
    )
    assert result["world_brief"]["setting"] == "No magic"
    result["world_brief"]["setting"] = "Changed copy"
    assert original["world_brief"]["setting"] == "No magic"
