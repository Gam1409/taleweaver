"""Autogenerate policy for data-recovery tables intentionally unmanaged by the ORM."""

from typing import Any


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    # This migration-owned archive contains verbatim orphaned records. An ORM
    # metadata diff must never propose destroying the only recovery copy.
    return not (
        type_ == "table"
        and name == "referential_repair_archive"
        and reflected
        and compare_to is None
    )
