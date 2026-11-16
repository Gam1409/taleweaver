"""Response policies preserve supported browser features without opening other origins."""

import pytest
from httpx import AsyncClient

from backend.core.config import settings


async def test_microphone_is_available_only_to_the_application_origin(client: AsyncClient):
    response = await client.get("/api/health")
    policy = response.headers["Permissions-Policy"]
    assert "microphone=(self)" in policy
    for feature in ("camera", "geolocation", "payment", "usb"):
        assert f"{feature}=()" in policy


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
async def test_patch_preflight_is_allowed_for_the_configured_frontend(client: AsyncClient, host):
    origin = f"http://{host}:{settings.FRONTEND_PORT}"
    response = await client.options(
        "/api/adventures/example",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "PATCH" in response.headers["access-control-allow-methods"]


async def test_patch_preflight_does_not_authorize_an_untrusted_origin(client: AsyncClient):
    response = await client.options(
        "/api/adventures/example",
        headers={"Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "PATCH"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
