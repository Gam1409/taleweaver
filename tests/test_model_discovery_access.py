"""Model discovery must not let readers redirect shared provider credentials."""

from dataclasses import dataclass

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.api.routes import config_api
from backend.core.auth import create_user_access_token
from backend.core.config import settings
from backend.core.security import encryption_util
from backend.models.user import User
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio
CASES = [
    ("llm-models", provider) for provider in (*config_api._OPENAI_COMPATIBLE_PROVIDERS, "minimax")
] + [("minimax-models", "minimax")]
FIXTURE_KEY = "neutral-model-discovery-fixture"
ALTERNATE_BASE = "https://alternate.example/v1"


@dataclass
class DiscoveryFixture:
    reader: dict[str, str]
    admin: dict[str, str]
    requests: list[httpx.Request]


@pytest_asyncio.fixture
async def discovery(monkeypatch):
    providers = (*config_api._OPENAI_COMPATIBLE_PROVIDERS, "minimax")
    async with TestSessionLocal() as db:
        admin = User(
            username="discovery_admin",
            hashed_password="unused",
            role="admin",
            encrypted_api_keys={
                provider: encryption_util.encrypt_key(FIXTURE_KEY) for provider in providers
            },
        )
        reader = User(username="discovery_reader", hashed_password="unused", role="user")
        db.add_all([admin, reader])
        await db.commit()
        headers = [
            {"Authorization": f"Bearer {create_user_access_token(user)}"}
            for user in (reader, admin)
        ]
    requests = []

    async def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "fixture-model"}]})

    original_client = httpx.AsyncClient

    def isolated_client(*args, **kwargs):
        return original_client(*args, **kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(config_api.httpx, "AsyncClient", isolated_client)
    return DiscoveryFixture(*headers, requests)


def request_params(endpoint, provider, **extra):
    return {**({"provider": provider} if endpoint == "llm-models" else {}), **extra}


def configured_base(provider):
    if provider == "minimax":
        return settings.MINIMAX_API_BASE
    return config_api._OPENAI_COMPATIBLE_PROVIDERS[provider]["default_base"]


@pytest.mark.parametrize("endpoint,provider", CASES)
@pytest.mark.parametrize("key_source", ["database", "environment"])
async def test_reader_cannot_redirect_shared_credentials(
    client, discovery, monkeypatch, endpoint, provider, key_source
):
    if key_source == "environment":
        async with TestSessionLocal() as db:
            admin = await db.scalar(select(User).where(User.role == "admin"))
            admin.encrypted_api_keys = {}
            await db.commit()
        monkeypatch.setattr(settings, f"{provider.upper()}_API_KEY", FIXTURE_KEY)
    response = await client.get(
        f"/api/settings/{endpoint}",
        headers=discovery.reader,
        params=request_params(endpoint, provider, api_base=ALTERNATE_BASE),
    )
    assert response.status_code == 403
    assert discovery.requests == []


@pytest.mark.parametrize("endpoint,provider", CASES)
@pytest.mark.parametrize("explicit_base", [False, True])
async def test_reader_can_discover_models_at_the_configured_endpoint(
    client, discovery, endpoint, provider, explicit_base
):
    base = configured_base(provider).rstrip("/")
    extra = {"api_base": base + "/"} if explicit_base else {}
    response = await client.get(
        f"/api/settings/{endpoint}",
        headers=discovery.reader,
        params=request_params(endpoint, provider, **extra),
    )
    assert response.status_code == 200
    assert response.json() == {"models": ["fixture-model"]}
    assert len(discovery.requests) == 1
    assert str(discovery.requests[0].url) == base + "/models"
    assert discovery.requests[0].headers["Authorization"] == f"Bearer {FIXTURE_KEY}"


@pytest.mark.parametrize("endpoint,provider", CASES)
async def test_admin_can_discover_models_at_an_alternate_endpoint(
    client, discovery, endpoint, provider
):
    response = await client.get(
        f"/api/settings/{endpoint}",
        headers=discovery.admin,
        params=request_params(endpoint, provider, api_base=ALTERNATE_BASE),
    )
    assert response.status_code == 200
    assert response.json() == {"models": ["fixture-model"]}
    assert str(discovery.requests[0].url) == ALTERNATE_BASE + "/models"


async def test_minimax_uses_its_configured_base_for_reader_discovery(
    client, discovery, monkeypatch
):
    base = "https://configured.example/minimax"
    monkeypatch.setattr(settings, "MINIMAX_API_BASE", base)
    response = await client.get(
        "/api/settings/llm-models", headers=discovery.reader, params={"provider": "minimax"}
    )
    assert response.status_code == 200
    assert str(discovery.requests[0].url) == base + "/models"


@pytest.mark.parametrize("endpoint", ["llm-models", "minimax-models"])
async def test_model_discovery_requires_authentication(client, discovery, endpoint):
    response = await client.get(
        f"/api/settings/{endpoint}", params=request_params(endpoint, "minimax")
    )
    assert response.status_code == 401
    assert discovery.requests == []


async def test_reader_cannot_override_legacy_minimax_with_a_supplied_key(client, discovery):
    response = await client.get(
        "/api/settings/minimax-models",
        headers=discovery.reader,
        params={"api_base": ALTERNATE_BASE, "api_key": "neutral-supplied-fixture"},
    )
    assert response.status_code == 403
    assert discovery.requests == []
