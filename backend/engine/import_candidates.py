"""Read local import candidates in a worker before checking database ownership."""

import json
import logging
import os
import zipfile

from backend.engine.archive_safety import validate_archive

logger = logging.getLogger(__name__)


def _read_candidate(path: str) -> tuple[str | None, str | None]:
    if path.endswith(".adz"):
        with zipfile.ZipFile(path) as archive:
            validate_archive(archive)
            payload = json.loads(archive.read("adventure.adv"))
        adventure = payload.get("adventure") or {}
        return adventure.get("title"), adventure.get("origin_id") or payload.get("origin_id")
    with open(path, encoding="utf-8") as source:
        payload = json.load(source)
    adventure = payload.get("adventure", {}) if payload.get("type") == "SESSION_BUNDLE" else payload
    return adventure.get("title"), adventure.get("origin_id")


def scan_import_candidates(directories: list[str]) -> list[tuple[str, str | None]]:
    candidates = []
    for directory in directories:
        candidates.extend(_scan_directory(directory))
    return candidates


def _scan_directory(directory: str) -> list[tuple[str, str | None]]:
    if not os.path.exists(directory):
        return []
    candidates = []
    for filename in os.listdir(directory):
        if not filename.endswith((".adv", ".adz")):
            continue
        path = os.path.join(directory, filename)
        try:
            title, origin_id = _read_candidate(path)
            if title:
                candidates.append((title, origin_id))
        except Exception:
            logger.exception("Error checking import file %s", path)
    return candidates
