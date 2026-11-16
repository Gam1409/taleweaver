"""Isolated HTTP fixture: real editor/auth/SQL routes, deterministic model replies.

Run with uvicorn tests.browser_ai_fix:app --host 127.0.0.1 --port 8019.
This module is never imported by the production application.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.api.routes.adventures.editing import ai_fix_llm
from backend.api.routes.adventures.editor import router
from backend.core.auth import create_access_token
from backend.core.config import settings
from backend.core.database import get_db
from backend.models.base import Base
from backend.models.user import User
from tests.ai_fix_fixture import TEMPLATE, proposal, seed
from tests.llm_fakes import RoleLLMFactory

engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
sessions = async_sessionmaker(engine, expire_on_commit=False)
calls = []


class Model:
    def __init__(self, *args, **kwargs):
        pass

    async def aexecute_complex_task(self, *, response_model, user_prompt, **kwargs):
        calls.append(user_prompt)
        if len(calls) == 1:
            raise RuntimeError("Controlled first-attempt failure")
        suggested = proposal()
        if len(calls) == 2:
            suggested["patches"][0]["field_updates"]["outfit"][0]["clothing"]["layer"] = 9
        return response_model.model_validate({"proposals": [suggested]})


@asynccontextmanager
async def lifespan(app):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        owner = User(username="ai_fix_browser", hashed_password="fixture", role="admin")
        db.add(owner)
        await db.flush()
        await seed(db, owner)
    settings.AI_FIX_FALLBACK_PROVIDER = ""
    original = ai_fix_llm.GameMasterLLM
    ai_fix_llm.GameMasterLLM = RoleLLMFactory(Model)
    try:
        yield
    finally:
        ai_fix_llm.GameMasterLLM = original
        await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(router, prefix="/api/adventures")


async def database():
    async with sessions() as db:
        yield db


app.dependency_overrides[get_db] = database


@app.get("/api/ai-fix-fixture/bootstrap")
async def bootstrap():
    return {"template_id": TEMPLATE, "token": create_access_token({"sub": "ai_fix_browser"})}


@app.get("/api/ai-fix-fixture/audit")
async def audit():
    return {"model_calls": len(calls)}
