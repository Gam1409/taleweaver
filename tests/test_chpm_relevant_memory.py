"""Relevant beliefs and opposing grounds must survive bounded historical views."""

from backend.engine.chpm import appraisal_context, development_context
from tests.test_chpm_appraisal import accept, heard, proposal
from tests.test_chpm_development import accept as develop
from tests.test_chpm_development import history
from tests.test_chpm_development import proposal as development_proposal


def contested_history():
    value = accept(heard(), [proposal()])
    value = heard(value, "explanation", "An emergency delayed me")
    value = accept(
        value,
        [
            proposal(
                belief_id="b1",
                stance="challenge",
                citations=[{"source_id": "e2", "quote": "emergency delayed me"}],
            )
        ],
        "explanation",
    )
    for index in range(12):
        value = heard(value, f"noise{index}", f"Routine discussion {index}.")
    return value


def test_old_support_and_counterevidence_replace_unrelated_recall_slots():
    value = contested_history()
    before = value.model_dump_json()
    window = appraisal_context.build(value, query="promise", recent_limit=2, recall_limit=2)
    historic = [s for s in window.payload["visible_evidence"] if s["source_id"].startswith("r")]
    assert len(historic) == 2
    assert {s["source_message_id"] for s in historic} == {"m1", "explanation"}
    assert {
        stance for s in historic for stances in s["basis_for"].values() for stance in stances
    } == {"support", "challenge"}
    assert all(s["kind"] == "reported" for s in historic)
    assert len(window.sources) == 4 and value.model_dump_json() == before


def test_ordinary_beliefs_are_filtered_before_the_budget_is_applied():
    value = history(speaker="@player")
    visible = appraisal_context.build(value).sources
    alias = next(iter(visible))
    value = accept(value, [proposal(citations=[{"source_id": alias, "quote": visible[alias][2]}])])
    for domain in ("reliability", "competence", "benevolence", "affection", "boundaries"):
        value, _ = develop(
            value,
            development_proposal(
                value,
                category="relationship",
                about_id="@player",
                relationship_domain=domain,
                statement=f"Developing {domain}",
            ),
            "develop-" + domain,
        )
    window = appraisal_context.build(value, belief_limit=2)
    assert [b.statement for b in window.beliefs.values()] == ["Promises may be unreliable"]


def test_current_speaker_and_topic_outweigh_newer_unrelated_beliefs():
    value = accept(heard(), [proposal()])
    value = heard(value, "other", "I prefer gardening", speaker="other")
    for index in range(10):
        value = accept(
            value,
            [
                proposal(
                    about_id="other",
                    statement=f"Gardening expectation {index}",
                    citations=[{"source_id": "e2", "quote": "prefer gardening"}],
                )
            ],
            f"belief-{index}",
        )
    value = heard(value, "current", "What about the promise?")
    window = appraisal_context.build(
        value, query="promise", current_message_id="current", belief_limit=1
    )
    assert [b.about_id for b in window.beliefs.values()] == ["@player"]
    assert len(window.beliefs) == 1


def test_small_recall_budget_keeps_a_counterexample_and_never_changes_the_belief():
    value = contested_history()
    window = appraisal_context.build(value, recent_limit=1, recall_limit=1)
    old = [source for alias, (_, source, _) in window.sources.items() if alias.startswith("r")]
    assert [s.message_id for s in old] == ["explanation"]
    assert value.snapshot.beliefs[0].status == "challenged"


def test_development_sample_retains_own_dated_speech_in_a_busy_history():
    from backend.engine.chpm.host_state import record
    from tests.test_chpm_host_state import source

    value = history((1, 1441, 2881), ("room", "other", "room"))
    own_ids = {s.message_id for s in value.sources.values() if s.kind == "speech"}
    for index in range(40):
        value = record(
            value,
            source(f"noise{index}", f"Other speech {index}").model_copy(
                update={"speaker_id": "@player", "role": "user"}
            ),
            minute=3000 + index,
        )
    episodes = development_context.episodes(value)
    assert len(episodes) <= 9
    assert own_ids <= {e.source.message_id for e in episodes.values()}
    own = [e for e in episodes.values() if e.source.speaker_id == "npc"]
    assert development_context.spans(own, development_context.DAY)


def test_long_source_keeps_negation_around_the_exact_support_quote():
    from backend.engine.chpm import appraisal

    value = heard(text="Routine background. " * 30 + "I did not promise to return.")
    window = appraisal_context.build(value)
    value, _ = appraisal.accept(
        value,
        [proposal(citations=[{"source_id": "e1", "quote": "promise to return"}])],
        window,
        message_id="m1",
    )
    for index in range(10):
        value = heard(value, f"noise{index}", f"Routine {index}.")
    recalled = appraisal_context.build(value, recent_limit=1, recall_limit=1)
    text = next(text for alias, (_, _, text) in recalled.sources.items() if alias.startswith("r"))
    assert text == "I did not promise to return."


def test_recent_ground_outside_the_excerpt_prefix_keeps_its_surrounding_negation():
    value = heard(text="Routine background. " * 30 + "I did not promise to return.")
    value = accept(value, [proposal(citations=[{"source_id": "e1", "quote": "promise to return"}])])
    value = heard(value, "current", "What happened?")
    window = appraisal_context.build(
        value, current_message_id="current", excerpt_chars=100, recall_limit=0
    )
    visible = window.payload["visible_evidence"]
    historical = next(s for s in visible if s["source_message_id"] == "m1")
    assert historical["text"] == "I did not promise to return."
    assert historical["basis_for"] == {"b1": ["support"]}
    assert historical["excerpted"]
    assert (
        next(s for s in visible if s["source_message_id"] == "current")["text"] == "What happened?"
    )


def test_explicit_present_subject_takes_priority_without_adding_names_to_model_context():
    from backend.engine.chpm.belief_recall import subjects

    value = accept(heard(), [proposal()])
    value = heard(value, "other", "I can inspect the bridge", speaker="engineer")
    value = accept(
        value,
        [
            proposal(
                about_id="engineer",
                domain="competence",
                statement="Can inspect the bridge",
                citations=[{"source_id": "e2", "quote": "inspect the bridge"}],
            )
        ],
        "other",
    )
    value = heard(value, "current", "What about Boris and the bridge?")
    focus = subjects(value, "What about Boris and the bridge?", "current", {"engineer": "Boris"})
    assert focus == ("engineer", "@player")
    window = appraisal_context.build(
        value, current_message_id="current", belief_limit=1, focus_subjects=focus
    )
    assert [b.about_id for b in window.beliefs.values()] == ["engineer"]
