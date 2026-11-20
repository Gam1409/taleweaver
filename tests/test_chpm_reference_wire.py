"""The generated wire selects source IDs while canonical owners retain exact prose."""

from types import SimpleNamespace

from backend.engine.chpm import cognitive_proposal, passages, rendering
from backend.engine.chpm.json_contract import response_schema
from backend.engine.chpm.schema import AgendaIntent, Settings
from tests.test_chpm_appraisal import heard
from tests.test_chpm_kernel import observation
from tests.test_chpm_runtime import prepared as prepared_host
from tests.test_chpm_semantic_choice import fixture


def proposal_context():
    mind, _, _, _ = fixture()
    mind = heard(mind, message="input", text="The bridge is ready.")
    return cognitive_proposal.prepare(
        SimpleNamespace(game_id="session"),
        Settings(mode="live", actor_ids=["npc"]),
        "npc",
        observation(),
        {},
        [],
        mind,
        None,
        pinned={},
        pinned_beliefs={},
        focus=(),
        hits=[],
        audit=[],
        notebook=None,
    )


def test_actual_proposal_schema_requires_references_instead_of_copied_evidence():
    request = proposal_context()
    schema = response_schema(request.schema, request.identifiers)
    fields = {
        key
        for definition in schema.get("$defs", {}).values()
        for key in definition.get("properties", {})
    }
    assert "quote" not in fields
    assert "fragment_id" in fields
    assert "reference_scope" in schema["required"]


async def test_actual_review_has_one_shared_spoken_anchor(monkeypatch):
    host = prepared_host()
    turn = host._chpm_turn
    turn.decisions["npc"].selected.agenda_change = AgendaIntent(
        action="commitment", text="Repair the bridge"
    )
    text = 'Rin: "Thanks. I will repair the bridge."'

    async def request(
        _manager, _settings, _usage, _instruction, payload, schema, *_args, **_kwargs
    ):
        assert "agenda_evidence" not in schema.model_json_schema()["properties"]
        selected = next(key for key, value in payload["passages"].items() if "I will" in value)
        return schema.model_validate(
            {
                "review_scope": payload["review_scope"],
                "matches": True,
                "evidence": [{"actor_id": "npc", "passage_id": selected}],
            }
        )

    monkeypatch.setattr(rendering.inference, "request", request)
    verdict = await rendering._review(host, turn, text, "")
    assert verdict.matches
    assert verdict.evidence[0].quote == verdict.agenda_evidence[0].quote
    assert verdict.evidence[0].quote in passages.index(text).values()
