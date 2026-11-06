"""Archive assets cannot turn imported image URLs into arbitrary file reads."""

import io
import json
from zipfile import ZipFile

import pytest
from PIL import Image

from backend.core.config import settings
from backend.engine.export_archives import pack_export_adz


def manifest(url):
    return {
        "adventure": {"image_url": url},
        "protagonist": None,
        "scenes": [],
        "npcs": [],
        "objects": [],
    }


def image_file(root, relative, *, svg=False):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if svg:
        path.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>')
    else:
        Image.new("RGB", (8, 8), "blue").save(path, format="PNG")
    return path


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize(
    "relative",
    [
        "private.db",
        "private.json",
        "adventures/library/OWN/renamed.png",
        "adventures/library/OWN/renamed.svg",
    ],
)
def test_non_media_and_renamed_database_are_rejected(data_root, relative):
    path = data_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"SQLite format 3\x00HARMLESS SENTINEL")
    with pytest.raises(ValueError):
        pack_export_adz(manifest("/data/" + relative), "OWN")


@pytest.mark.parametrize(
    "relative",
    [
        "adventures/library/OTHER/image.png",
        "adventures/sessions/other-session/image.png",
        "internal/image.png",
    ],
)
def test_other_private_scopes_are_rejected_even_for_valid_images(data_root, relative):
    image_file(data_root, relative)
    with pytest.raises(ValueError):
        pack_export_adz(manifest("/data/" + relative), "OWN")


@pytest.mark.parametrize("relative", ["private.db", "adventures/library/OTHER/missing.png"])
def test_forbidden_missing_references_are_rejected_without_a_file_existence_oracle(
    data_root, relative
):
    with pytest.raises(ValueError):
        pack_export_adz(manifest("/data/" + relative), "OWN")


@pytest.mark.parametrize(
    "relative,svg",
    [
        ("adventures/library/OWN/portrait.png", False),
        ("adventures/OWN/portrait.png", False),
        ("catalog/styles/default.png", False),
        ("characters/portrait.png", False),
        ("adventures/library/OWN/placeholder.svg", True),
        ("adventures/library/OWN/placeholder.jpg", True),
    ],
)
def test_own_legacy_and_shared_images_remain_portable(data_root, relative, svg):
    path = image_file(data_root, relative, svg=svg)
    raw = pack_export_adz(manifest("/data/" + relative), "OWN")
    with ZipFile(io.BytesIO(raw)) as archive:
        exported = json.loads(archive.read("adventure.adv"))
        assert archive.read(exported["adventure"]["image_url"]) == path.read_bytes()


def test_same_basename_images_get_distinct_archive_names(data_root):
    first = image_file(data_root, "adventures/library/OWN/a/image.png")
    second = image_file(data_root, "adventures/library/OWN/b/image.png")
    Image.new("RGB", (8, 8), "red").save(second)
    value = manifest("/data/adventures/library/OWN/a/image.png")
    value["scenes"] = [{"image_url": "/data/adventures/library/OWN/b/image.png"}]
    raw = pack_export_adz(value, "OWN")
    with ZipFile(io.BytesIO(raw)) as archive:
        exported = json.loads(archive.read("adventure.adv"))
        cover, scene = exported["adventure"]["image_url"], exported["scenes"][0]["image_url"]
        assert cover != scene
        assert archive.read(cover) == first.read_bytes()
        assert archive.read(scene) == second.read_bytes()
        assert len(archive.namelist()) == len(set(archive.namelist()))


def test_symlink_cannot_escape_the_authorized_adventure(data_root):
    target = image_file(data_root, "adventures/library/OTHER/image.png")
    link = data_root / "adventures/library/OWN/image.png"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    with pytest.raises(ValueError):
        pack_export_adz(manifest("/data/adventures/library/OWN/image.png"), "OWN")


def test_svg_dtd_and_external_entities_are_rejected(data_root):
    path = data_root / "adventures/library/OWN/image.svg"
    path.parent.mkdir(parents=True)
    path.write_bytes(b'<!DOCTYPE svg [<!ENTITY e SYSTEM "file:///not-read">]><svg>&e;</svg>')
    with pytest.raises(ValueError):
        pack_export_adz(manifest("/data/adventures/library/OWN/image.svg"), "OWN")


async def test_imported_reference_cannot_read_a_private_data_file(auth_client, data_root):
    (data_root / "private.db").write_bytes(b"ONLY A TEST SENTINEL")
    payload = {
        "version": "1.0",
        "type": "SESSION_BUNDLE",
        "adventure": {
            "title": "Reference test",
            "image_url": "/data/private.db",
            "original_manifest": {"version": "1.0"},
        },
        "scenes": [],
        "exits": [],
        "entities": [],
        "game_state": None,
        "avatar": None,
        "chat_history": [],
    }
    imported = await auth_client.post("/api/adventures/import/session-bundle", json=payload)
    assert imported.status_code == 200, imported.text
    identifier = imported.json()["adventure_id"]
    response = await auth_client.get(f"/api/adventures/{identifier}/export/adz")
    assert response.status_code == 404, response.text
    assert "ONLY A TEST SENTINEL" not in response.text
