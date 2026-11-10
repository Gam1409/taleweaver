"""Requested output modes are traceable without recording any schema or story text."""

from backend.core import llm_diagnostics
from backend.core.diagnostic_fields import safe_fields
from backend.core.llm_structured_output import trace


def test_output_contract_logs_only_mode_fingerprint_and_count(monkeypatch):
    secret = "PRIVATE_SOURCE_AND_MODEL_INSTRUCTION"
    records = []
    monkeypatch.setattr(
        llm_diagnostics, "emit", lambda event, **fields: records.append((event, fields))
    )
    payload = {
        "type": "json_schema",
        "json_schema": {"schema": {"type": "object", "description": secret}},
    }
    trace(payload, local_checks=("pattern",))
    trace(payload)
    assert secret not in str(records)
    event, fields = records[0]
    assert event == "llm.output_contract"
    assert fields["output_mode"] == "json_schema" and fields["local_check_count"] == 1
    assert len(fields["schema_fingerprint"]) == 64
    assert fields["schema_fingerprint"] == records[1][1]["schema_fingerprint"]
    assert safe_fields(fields) == fields
    assert safe_fields({"schema_fingerprint": secret, "output_mode": secret}) == {}
