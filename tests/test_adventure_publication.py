"""Publication uses copies, requires explicit loss acknowledgement and excludes unused files."""

import io
import json
import zipfile
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from backend.api.routes.adventures import publication
from backend.services.adventure_publication import bundle
from scripts.prepare_adventure_publication import main
from tests.test_session_portraits import portrait_world

__all__ = ["portrait_world"]


@dataclass
class Report:
    warnings: list[str]
    requires_acknowledgement: bool
    source_format: str = "fork"
    target_format: str = "upstream"


def archive(manifest=None, **assets):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as output:
        output.writestr("adventure.adv", json.dumps(manifest or {"adventure": {"title": "Мир"}}))
        for name, value in assets.items():
            output.writestr(name, value)
    return data.getvalue()


@pytest.fixture
def converter(monkeypatch):
    def convert(manifest):
        return {"adventure": manifest["adventure"]}, Report([], False)

    monkeypatch.setattr(bundle, "export_upstream_manifest", convert)


def test_archive_keeps_only_referenced_assets_and_unicode(converter):
    original = archive(
        {"adventure": {"title": "Мир", "image_url": "assets/обложка.png"}},
        **{"assets/обложка.png": b"image", "assets/unused.txt": b"private extra"},
    )
    converted, report = bundle.prepare_bundle(original)
    with zipfile.ZipFile(io.BytesIO(converted)) as output:
        assert set(output.namelist()) == {"adventure.adv", "assets/обложка.png"}
        assert json.loads(output.read("adventure.adv"))["adventure"]["title"] == "Мир"
    assert report["asset_count"] == 1
    with zipfile.ZipFile(io.BytesIO(original)) as source:
        assert "assets/unused.txt" in source.namelist()


@pytest.mark.parametrize("name", ["../secret", "assets/../../secret", "/assets/foo", "assets\\foo"])
def test_unsafe_paths_rejected_even_if_unreferenced(name, converter):
    with pytest.raises(bundle.PublicationError, match="unsafe"):
        bundle.prepare_bundle(archive(**{name: b"bad"}))


def test_missing_local_asset_and_missing_archive_asset_rejected(converter):
    for value in [
        "/data/missing.png",
        "assets/missing.png",
        "http://localhost/private.png?key=secret",
    ]:
        with pytest.raises(bundle.PublicationError, match="asset"):
            bundle.prepare_bundle(archive({"adventure": {"image_url": value}}))


def test_saved_session_archive_without_blueprint_rejected():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as source:
        source.writestr("session.ads", "{}")
    with pytest.raises(bundle.PublicationError):
        bundle.prepare_bundle(output.getvalue())


def test_cli_preview_writes_nothing_and_never_overwrites_source(tmp_path, converter, capsys):
    source = tmp_path / "source.adz"
    original = archive()
    source.write_bytes(original)
    assert main([str(source)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.adz"]
    assert main([str(source), "--output", str(source)]) == 1
    assert source.read_bytes() == original
    target = tmp_path / "public.adz"
    assert main([str(source), "--output", str(target)]) == 0
    assert target.exists()
    assert "compatible" in capsys.readouterr().out


def test_cli_requires_explicit_compatibility_ack(tmp_path, monkeypatch):
    monkeypatch.setattr(
        bundle, "export_upstream_manifest", lambda m: (m, Report(["VN becomes Chat"], True))
    )
    source, target = tmp_path / "source.adz", tmp_path / "public.adz"
    source.write_bytes(archive())
    assert main([str(source), "--output", str(target)]) == 1
    assert not target.exists()
    assert main([str(source), "--output", str(target), "--acknowledge-changes"]) == 0


async def test_api_owner_guard_preview_and_ack(auth_client, portrait_world, monkeypatch):
    export = AsyncMock(return_value=archive())
    monkeypatch.setattr(publication.AdventureExporter, "export_adz", export)
    monkeypatch.setattr(
        bundle, "export_upstream_manifest", lambda m: (m, Report(["VN becomes Chat"], True))
    )
    base = "/api/adventures/templates/portrait-template/publication"
    preview = await auth_client.get(base + "/preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["requires_acknowledgement"]
    rejected = await auth_client.post(base + "/export", json={})
    assert rejected.status_code == 409
    accepted = await auth_client.post(base + "/export", json={"acknowledge_changes": True})
    assert accepted.status_code == 200
    assert accepted.headers["content-type"] == "application/zip"
    assert zipfile.is_zipfile(io.BytesIO(accepted.content))
    export.reset_mock()
    missing = await auth_client.post(
        "/api/adventures/templates/not-owned/publication/export", json={"acknowledge_changes": True}
    )
    assert missing.status_code == 404
    export.assert_not_awaited()


def test_real_upstream_fixture_prepares_without_mutating_input():
    from pathlib import Path

    manifest = json.loads(
        Path("tests/fixtures/adventure_compat/upstream_choice.adv").read_text(encoding="utf-8")
    )
    # Source fixture is an unpublished blueprint; assign its publication identity.
    manifest["adventure"]["origin_id"] = "240b24ab-4639-41cb-8720-c876b98a2b68"
    original = archive(manifest)
    prepared, report = bundle.prepare_bundle(original)
    assert report["compatible"] is True
    assert report["source_mode"] == report["target_mode"] == "chat"
    with zipfile.ZipFile(io.BytesIO(prepared)) as result:
        converted = json.loads(result.read("adventure.adv"))
    assert converted["adventure"]["title"] == manifest["adventure"]["title"]
    assert converted["scripts"] == manifest["scripts"]
    with zipfile.ZipFile(io.BytesIO(original)) as source:
        assert json.loads(source.read("adventure.adv")) == manifest


async def test_foreign_template_is_not_exported(auth_client, portrait_world, monkeypatch):
    from backend.models.adventure_template import AdventureTemplate
    from backend.models.user import User
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        db.add(
            User(id="publication-other", username="publication-other", hashed_password="test-only")
        )
        await db.flush()
        template = await db.get(AdventureTemplate, "portrait-template")
        template.owner_id = "publication-other"
        await db.commit()
    export = AsyncMock()
    monkeypatch.setattr(publication.AdventureExporter, "export_adz", export)
    base = "/api/adventures/templates/portrait-template/publication"
    assert (await auth_client.get(base + "/preview")).status_code == 404
    assert (
        await auth_client.post(base + "/export", json={"acknowledge_changes": True})
    ).status_code == 404
    export.assert_not_awaited()


async def test_actual_exporter_prepares_template_without_session_history(
    auth_client, portrait_world
):
    from backend.models.adventure_template import AdventureTemplate
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        template.rule_enforcement_mode = "chat"
        template.version = "1.0.0"
        await db.commit()
    base = "/api/adventures/templates/portrait-template/publication"
    response = await auth_client.post(base + "/export", json={"acknowledge_changes": True})
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as output:
        manifest = json.loads(output.read("adventure.adv"))
    assert manifest["adventure"]["title"] == "Forest"
    assert manifest["adventure"]["origin_id"]
    assert "session_state" not in manifest and "chat_messages" not in manifest
    async with TestSessionLocal() as db:
        template = await db.get(AdventureTemplate, "portrait-template")
        assert template.rule_enforcement_mode == "chat"
