"""Portable adventure conversion; archive ownership and extraction stay with callers."""

from backend.engine.adventure_compat.common import CompatibilityError, ConversionReport
from backend.engine.adventure_compat.inbound import import_upstream_manifest
from backend.engine.adventure_compat.outbound import export_upstream_manifest

__all__ = [
    "CompatibilityError",
    "ConversionReport",
    "export_upstream_manifest",
    "import_upstream_manifest",
]
