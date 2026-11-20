"""Saved command placements remain verifiable without comparing a command to prose."""

from types import SimpleNamespace

from backend.engine.clothing.changes import preview
from backend.engine.narrated_items.observation_sources import verified_sources
from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.narrated_items.wear import unchanged_observation
from backend.models.chat import ChatMessage
from tests.conftest import TestSessionLocal
from tests.test_command_wear_provenance import INPUT, actor, proof
from tests.test_vn_turn_integration import seed_vn


async def test_command_input_proof_survives_later_narration_but_not_input_edits():
    async with TestSessionLocal() as db:
        await seed_vn(db)
        source = ChatMessage(
            id="input", session_id="session-1", role="user", content=INPUT, revision_id="revision"
        )
        db.add(source)
        await db.commit()
        changed = preview(actor(), "COAT", "adjust", ["arms"], detailed=False, proof=proof())
        extraction = ItemExtraction(
            actions=[
                {
                    "item_id": "COAT",
                    "source_owner": "npc",
                    "destination_owner": "npc",
                    "disposition": "worn",
                    "basis": "observed_wear",
                    "uncovered_regions": ["arms"],
                    "evidence": "The coat remains displaced.",
                }
            ]
        )
        host = SimpleNamespace(db=db, state=SimpleNamespace(session_id="session-1"))
        current = await verified_sources(host, extraction, {"npc": changed})
        assert current == {("npc", "COAT")}
        assert unchanged_observation(
            extraction.actions[0],
            changed,
            "COAT",
            narration="The coat remains displaced.",
            verified_sources=current,
        )
        host.state.session_id = "another-session"
        assert await verified_sources(host, extraction, {"npc": changed}) == set()
        host.state.session_id = "session-1"
        source.content = "Edited input."
        await db.commit()
        assert await verified_sources(host, extraction, {"npc": changed}) == set()
