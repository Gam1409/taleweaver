"""Settings writes must not broadcast stale snapshots of unrelated configuration."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from backend.api.routes import config_api, memory_settings
from backend.models.user import User
from tests.conftest import TestSessionLocal

LLM = {
    "small_model": "new-small",
    "small_model_provider": "ollama",
    "complex_model": "new-large",
    "complex_model_provider": "ollama",
    "preferred_provider": "ollama",
}
MEMORY = {
    "enabled": False,
    "provider": "ollama",
    "base_url": "http://localhost:11434",
    "model": "new-embedding",
}


async def seed():
    async with TestSessionLocal() as db:
        for identifier, role in [("settings-admin", "admin"), ("settings-peer", "user")]:
            db.add(
                User(
                    id=identifier,
                    username=identifier,
                    hashed_password="test",
                    role=role,
                    llm_settings={
                        "small_model": "old-small",
                        "memory_rag": {"model": "old-embedding"},
                    },
                    t2i_settings={"simple_model": "old-image"},
                    encrypted_api_keys={"memory_embeddings": "old-key"},
                )
            )
        await db.commit()


async def test_stale_llm_save_preserves_new_image_settings_for_every_user():
    await seed()
    async with TestSessionLocal() as stale, TestSessionLocal() as current:
        owner = await stale.get(User, "settings-admin")
        await stale.commit()  # Keep the request's old identity-map values.
        fresh = await current.get(User, "settings-admin")
        payload = config_api.T2ISettingsPayload(
            simple_model="new-image",
            simple_model_provider="openai",
            advanced_model="new-image",
            advanced_model_provider="openai",
            provider="openai",
        )
        await config_api.update_t2i_settings(payload, current, fresh)
        expected = deepcopy(fresh.t2i_settings)
        assert owner.t2i_settings["simple_model"] == "old-image"
        await config_api.update_llm_settings(config_api.SettingsPayload(**LLM), stale, owner)
    async with TestSessionLocal() as db:
        users = list(await db.scalars(select(User)))
        assert len(users) == 2
        for user in users:
            assert user.t2i_settings == expected
            assert user.llm_settings["small_model"] == "new-small"


@pytest.mark.parametrize("last", ["llm", "memory"])
async def test_stale_same_column_merges_preserve_new_completion_and_embedding_settings(last):
    await seed()
    async with TestSessionLocal() as stale, TestSessionLocal() as current:
        old_owner = await stale.get(User, "settings-admin")
        await stale.commit()
        fresh_owner = await current.get(User, "settings-admin")
        if last == "llm":
            await memory_settings.save_memory_settings(
                memory_settings.MemorySettingsPayload(**MEMORY), current, fresh_owner
            )
            await config_api.update_llm_settings(
                config_api.SettingsPayload(**LLM), stale, old_owner
            )
        else:
            await config_api.update_llm_settings(
                config_api.SettingsPayload(**LLM), current, fresh_owner
            )
            # A concurrent key edit must survive a memory settings save without a new key.
            fresh_owner.encrypted_api_keys = {
                "memory_embeddings": "new-key",
                "another_provider": "other-key",
            }
            await config_api._broadcast_global_settings(
                current, fresh_owner, fields=("encrypted_api_keys",)
            )
            await current.commit()
            await memory_settings.save_memory_settings(
                memory_settings.MemorySettingsPayload(**MEMORY), stale, old_owner
            )
    async with TestSessionLocal() as db:
        for user in await db.scalars(select(User)):
            assert user.llm_settings["small_model"] == "new-small"
            assert user.llm_settings["memory_rag"]["model"] == "new-embedding"
            if last == "memory":
                assert user.encrypted_api_keys == {
                    "memory_embeddings": "new-key",
                    "another_provider": "other-key",
                }
