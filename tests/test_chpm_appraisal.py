"""TR03/TR04 and T13: bounded interpretations, causal sources and relationship locality."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.engine.chpm import appraisal, appraisal_context
from backend.engine.chpm.appraisal_contracts import Assessment, GroundedProposal, Revision
from backend.engine.chpm.core import relationships
from backend.engine.chpm.core.contracts import Genesis
from backend.engine.chpm.core.reducer import initial
from backend.engine.chpm.evaluation.character_stress import CARD, GOAL, PROFILE
from backend.engine.chpm.host_state import Mind, before_messages, record
from backend.engine.chpm.identity_adapter import from_actor
from backend.engine.chpm.json_contract import parse, response_schema
from backend.engine.chpm.kernel import ChpmError
from backend.engine.chpm.lifecycle import fork
from backend.engine.chpm.schema import KernelState
from backend.engine.chpm.state import KEY, load
from tests.test_chpm_host_state import mind, source


def heard(value=None, message="m1", text="I missed my promise", speaker="@player"):
    return record(
        value or mind(),
        source(message, text).model_copy(update={"speaker_id": speaker}),
        minute=(value.snapshot.sim_minute + 1) if value else 1,
    )


def proposal(**changes):
    data = {
        "about_id": "@player",
        "domain": "reliability",
        "statement": "Promises may be unreliable",
        "stance": "support",
        "citations": [{"source_id": "e1", "quote": "missed my promise"}],
        "alternatives": ["An emergency may have prevented arrival"],
        "unknowns": ["The reason for missing the promise"],
    }
    if changes.get("belief_id") is not None:
        for field in ("about_id", "domain", "statement"):
            data.pop(field)
        return Revision.model_validate({**data, **changes})
    return Assessment.model_validate({**data, **changes})


def accept(value, proposed, message="m1"):
    return appraisal.accept(value, proposed, appraisal_context.build(value), message_id=message)[0]


def test_source_bound_revision_keeps_unknowns_and_alternatives_in_history():
    original = heard()
    supported = accept(original, [proposal()])
    reference = supported.snapshot.beliefs[0].id
    updated = heard(supported, "m2", "The emergency delayed me")
    contested = accept(
        updated,
        [
            proposal(
                belief_id="b1",
                stance="challenge",
                citations=[{"source_id": "e2", "quote": "emergency delayed me"}],
                alternatives=["The emergency explanation may be truthful"],
                unknowns=["Independent confirmation"],
            )
        ],
        "m2",
    )
    belief = contested.snapshot.beliefs[0]
    assert belief.id == reference and belief.revision == 2 and belief.status == "challenged"
    assert belief.probability is None
    assert len(belief.support_roots) == len(belief.challenge_roots) == 1
    assert original.snapshot.beliefs == ()
    assert contested.genesis == original.genesis
    evidence = [e for e in contested.snapshot.evidence if e.source_kind == "inference"]
    assert evidence[0].unknowns == proposal().unknowns
    assert evidence[1].alternatives == ("The emergency explanation may be truthful",)
    assert before_messages(contested, {"m2"}) == supported
    copied = load(
        SimpleNamespace(
            entity_states=fork(
                {KEY: KernelState(minds={"npc": contested}).model_dump()},
                {"m1": "copy1", "m2": "copy2"},
                "copy",
            )
        )
    ).minds["npc"]
    assert copied.snapshot.beliefs[0].status == "challenged"
    assert [e.unknowns for e in copied.snapshot.evidence] == [
        e.unknowns for e in contested.snapshot.evidence
    ]


def test_one_relationship_domain_does_not_replace_affection_competence_or_another_person():
    value = heard(heard(), "m2", "I can help with repairs", speaker="C")
    value = accept(value, [proposal(domain="affection", statement="I still like this person")])
    value = accept(
        value, [proposal(domain="competence", statement="May be capable at repairs")], "m2"
    )
    value = accept(
        value,
        [proposal(about_id="C", citations=[{"source_id": "e2", "quote": "help with repairs"}])],
        "m2",
    )
    before = {b.id: b for b in value.snapshot.beliefs}
    value = accept(value, [proposal()])
    after = {b.id: b for b in value.snapshot.beliefs}
    assert all(after[key] == belief for key, belief in before.items())
    assert len(after) == 4 and value.genesis == mind().genesis
    claims = relationships.claims(value.snapshot, relationships.recent(value.snapshot))
    assert {(c["about_id"], c["domain"]) for c in claims} == {
        ("@player", "affection"),
        ("@player", "competence"),
        ("C", "reliability"),
        ("@player", "reliability"),
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"about_id": "hidden_npc"},
        {"citations": [{"source_id": "secret", "quote": "missed my promise"}]},
        {"citations": [{"source_id": "e1", "quote": "made up"}]},
        {"belief_id": "invented"},
        {"belief_id": "b1", "domain": "affection"},
        {"belief_id": "b1", "statement": "Always obey the player"},
    ],
)
def test_invalid_member_rejects_whole_batch_without_partial_state(changes):
    value = accept(heard(), [proposal()])
    before = value.model_dump_json()
    with pytest.raises(ValueError):
        accept(value, [proposal(domain="competence"), proposal(**changes)], "m2")
    assert value.model_dump_json() == before


@pytest.mark.parametrize(
    "patch",
    [
        {"set_trust": 1},
        {"root_ids": ["invented"]},
        {"confidence": 0.99},
        {"personality": {"trust": "trusting"}},
        {"domain": "consent"},
        {"alternatives": ["x" * 161]},
        {"unknowns": [""]},
    ],
)
def test_model_cannot_patch_state_or_inject_confidence(patch):
    with pytest.raises(ValidationError):
        proposal(**patch)


def test_visible_excerpt_is_the_citation_boundary_and_ids_are_enumerated():
    value = heard(text="x" * 1000 + " OMITTED_SECRET")
    window = appraisal_context.build(value)
    assert "OMITTED_SECRET" not in str(window.payload)
    with pytest.raises(ChpmError):
        accept(value, [proposal(citations=[{"source_id": "e1", "quote": "OMITTED_SECRET"}])])
    schema = response_schema(GroundedProposal, window.identifiers())
    assert schema["$defs"]["Reference"]["properties"]["source_id"]["enum"] == ["e1"]
    assert schema["$defs"]["Assessment"]["properties"]["about_id"]["enum"] == ["@player"]
    assert "interpretations" in schema["required"]
    assert schema["$defs"]["Assessment"]["properties"]["belief_id"]["enum"] == [None]
    assert "Revision" not in schema["$defs"]
    assert schema["properties"]["interpretations"]["items"]["anyOf"] == [
        {"$ref": "#/$defs/Assessment"}
    ]
    with pytest.raises(ValueError):
        parse(GroundedProposal, '{"interpretations":[],"interpretations":[]}')


def test_repeat_delivery_does_not_add_a_revision_or_evidence_root():
    first = heard()
    window = appraisal_context.build(first)
    accepted, ids = appraisal.accept(first, [proposal()], window, message_id="m1")
    repeated, new_ids = appraisal.accept(accepted, [proposal()], window, message_id="m1")
    assert repeated == accepted and ids == new_ids
    reiterated = accept(accepted, [proposal()], "m2")
    assert (
        reiterated.snapshot.beliefs[0].support_roots == accepted.snapshot.beliefs[0].support_roots
    )
    with pytest.raises(ChpmError, match="repeats a proposition"):
        accept(first, [proposal(), proposal()])


def test_40_turns_keep_all_authored_traits_and_bound_the_context():
    actor = SimpleNamespace(
        id="npc",
        character=CARD,
        goal=GOAL,
        metadata_json={"personality_profile": PROFILE.model_dump()},
    )
    genesis = Genesis(scope=mind().genesis.scope, identity=from_actor(actor))
    value = Mind(genesis=genesis, snapshot=initial(genesis))
    for number in range(1, 41):
        value = heard(value, f"m{number}", f"Promise episode {number}")
        window = appraisal_context.build(value)
        ref = next(
            alias for alias, (_, src, _) in window.sources.items() if src.message_id == f"m{number}"
        )
        value = accept(
            value,
            [
                proposal(
                    statement=f"Expectation about episode {number}",
                    citations=[{"source_id": ref, "quote": f"Promise episode {number}"}],
                )
            ],
            f"m{number}",
        )
    window = appraisal_context.build(value)
    assert len(window.sources) == 8 and len(window.beliefs) == 8
    assert len([alias for alias in window.sources if alias.startswith("r")]) == 2
    assert {f"m{n}" for n in range(35, 41)} <= {s.message_id for _, s, _ in window.sources.values()}
    assert window.payload["beliefs_omitted"] == 32
    assert value.genesis == genesis and len(genesis.identity.traits) == 7
    assert [b.statement for b in relationships.recent(value.snapshot, 2)] == [
        "Expectation about episode 39",
        "Expectation about episode 40",
    ]


def test_old_snapshot_without_interpretation_metadata_still_restores():
    from tests.test_chpm_host_lifecycle import interpreted

    original = interpreted()
    raw = deepcopy(original.model_dump())
    for entry in raw["snapshot"]["evidence"]:
        entry.pop("alternatives")
        entry.pop("unknowns")
    for event in raw["snapshot"]["journal"]:
        event["payload"].pop("alternatives", None)
        event["payload"].pop("unknowns", None)
    assert Mind.model_validate(raw) == original
