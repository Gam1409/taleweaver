"""Read controller selection without replaying unrelated psychological ledgers."""

from typing import Any

from pydantic import TypeAdapter

from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.schema import KernelState, Settings, migrate_kernel_envelope

_VERSION: TypeAdapter[Any] = TypeAdapter(KernelState.model_fields["schema_version"].annotation)


def read(raw: Any) -> Settings:
    if raw is None:
        return Settings()
    envelope = migrate_kernel_envelope(raw)
    if not isinstance(envelope, dict):
        raise ChpmError("Invalid NPC Personality settings envelope.")
    _VERSION.validate_python(
        envelope.get("schema_version", KernelState.model_fields["schema_version"].default)
    )
    return Settings.model_validate(envelope.get("settings", {}))
