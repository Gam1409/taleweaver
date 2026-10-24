"""Stable IDs for older catalog entries that have no saved identifier."""

from uuid import NAMESPACE_URL, uuid5


def legacy_catalog_id(name: str) -> str:
    # Reads must not allocate a different ID on each settings reload.
    return str(uuid5(NAMESPACE_URL, f"taleweaver:catalog:{name.strip()}"))
