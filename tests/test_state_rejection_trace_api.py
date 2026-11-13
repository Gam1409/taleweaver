"""The rejection trace flag is persisted, strictly typed and admin-only."""

import pytest

from backend.core.system_diagnostics import service
from tests.state_trace_support import isolate_trace_directory


@pytest.fixture(autouse=True)
def isolated_diagnostics(tmp_path, monkeypatch):
    yield from isolate_trace_directory(tmp_path, monkeypatch)


async def test_admin_saves_independent_flag_and_master_off_clears_it(auth_client):
    response = await auth_client.put(
        "/api/system-diagnostics", json={"enabled": True, "state_failure_traces": True}
    )
    assert response.status_code == 200
    assert response.json()["state_failure_traces"] is True
    assert response.json()["detailed_logging"] is False
    assert (await auth_client.get("/api/system-diagnostics")).json()["state_failure_traces"] is True
    response = await auth_client.put(
        "/api/system-diagnostics", json={"enabled": False, "state_failure_traces": True}
    )
    assert response.status_code == 200
    assert response.json()["state_failure_traces"] is False
    response = await auth_client.put("/api/system-diagnostics", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["state_failure_traces"] is False


@pytest.mark.parametrize("value", ["true", "false", 1, 0, None])
async def test_rejection_trace_flag_rejects_coerced_values(auth_client, value):
    response = await auth_client.put(
        "/api/system-diagnostics", json={"enabled": True, "state_failure_traces": value}
    )
    assert response.status_code == 422
    assert service.enabled is False


async def test_non_admin_cannot_read_or_enable_rejection_traces(auth_client):
    from sqlalchemy import select

    from backend.models.user import User
    from tests.conftest import TestSessionLocal

    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
        user.role = "user"
        await db.commit()
    assert (await auth_client.get("/api/system-diagnostics")).status_code == 403
    response = await auth_client.put(
        "/api/system-diagnostics", json={"enabled": True, "state_failure_traces": True}
    )
    assert response.status_code == 403
    assert service.enabled is False
