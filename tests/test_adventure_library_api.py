"""Authenticated catalog browse/install endpoints never accept client-selected URLs."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.api.routes.adventures import library
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from backend.services.adventure_library.catalog import LibraryError
from backend.services.adventure_library.installer import AdventureInstallError
from backend.services.adventure_library.models import AdventureLibrary
from tests.test_adventure_library import entry

PREFIX = "/api/adventures/library"


@pytest.fixture
def catalog_stub(monkeypatch):
    service = library.LibraryService()
    service.get_library = AsyncMock(return_value=AdventureLibrary(schema=1, adventures=[entry()]))
    monkeypatch.setattr(library, "_library_service", service)
    monkeypatch.setattr(library, "_installing", set())
    return service


@pytest.mark.asyncio
async def test_catalog_reports_owned_version_update_and_refresh(
    auth_client, db_session, catalog_stub
):
    owner = await db_session.scalar(select(User.id).where(User.username == "test_user"))
    db_session.add(
        AdventureTemplate(title="Old title", owner_id=owner, origin_id=entry().id, version="1.0")
    )
    await db_session.commit()
    response = await auth_client.get(PREFIX + "/catalog")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["installed_version"] == "1.0" and item["update_available"]
    assert (await auth_client.post(PREFIX + "/refresh")).status_code == 200
    assert catalog_stub.get_library.call_args.kwargs["force_refresh"] is True


@pytest.mark.asyncio
async def test_install_calls_authorized_owner_and_rejects_url(
    auth_client, monkeypatch, catalog_stub
):
    install = AsyncMock(return_value="new-template")
    monkeypatch.setattr(library, "install_entry", install)
    response = await auth_client.post(PREFIX + "/install", json={"id": entry().id})
    assert response.json() == {"template_id": "new-template", "version": "2.0"}
    assert install.call_args.kwargs["owner_id"]
    assert (
        await auth_client.post(
            PREFIX + "/install", json={"id": entry().id, "url": "https://untrusted.test"}
        )
    ).status_code == 422
    install.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,status",
    [(LibraryError("offline"), 502), (AdventureInstallError("Unsupported behavior"), 422)],
)
async def test_install_failure_releases_owner_scoped_lock(
    auth_client, monkeypatch, catalog_stub, failure, status
):
    install = AsyncMock(side_effect=failure)
    monkeypatch.setattr(library, "install_entry", install)
    response = await auth_client.post(PREFIX + "/install", json={"id": entry().id})
    assert response.status_code == status
    assert library._installing == set()


@pytest.mark.asyncio
async def test_catalog_routes_require_authentication(client, catalog_stub):
    response = await client.get(PREFIX + "/catalog")
    assert response.status_code in {401, 403}
    catalog_stub.get_library.assert_not_awaited()
