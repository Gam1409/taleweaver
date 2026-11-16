# Narration flow guidance

The existing narrator presentation settings own `flow`: `off`, `gentle` (default),
or `balanced`. The addition uses existing manifest/session JSON. It does not add
a ledger, migration, extraction task, model request or output postprocessor.
Legacy writes that omit only the new field retain its current value, including a
frozen inherited preference. Explicit flow values use the normal validation, lease
and compare-and-swap guards. Existing voice/amount PUT semantics are unchanged.

## Measurement and budgets

`backend/engine/narrator/flow_metrics.py` produces an ephemeral `FlowReport` from
eligible completed assistant messages already loaded for narration. Player,
system, debug, foreign-session and explicitly incomplete messages are excluded
by the shared history adapter. Current saved revisions and the existing history
window remain authoritative after rewrites and full-turn replay.

Analysis is bounded to the most recent eight eligible replies, at most 2,000
characters and 320 tokens per reply: 16,000 characters and 2,560 tokens in total.
Truncation is reported. Exact full-reply lengths remain available without scanning
the full text; clipped prefixes cannot make different long replies look equal.
Clipped replies do not supply closing or whole-reply sentence-count observations.
History outside the existing memory window is not loaded to meet a threshold.

Measurements include recurring phrases, sentence openings, incidental gesture
patterns, repeated endings/questions, ellipses, dash interruptions and uniform
reply lengths/sentence counts. These are lexical and structural observations,
not semantic judgements about a character or plot. Quoted dialogue, speaker
attributions and known delivery cues are omitted from the measurement view;
the original history and generated output remain untouched.

Gentle needs at least four measurable narration replies. Balanced needs at least
three. Both require recurrence across multiple replies. The profile thresholds
are detection budgets, not numerical instructions imposed on the model. No new
sentence, punctuation, paragraph or response-length quota is introduced. Existing
task formatting and amount preferences still apply.

Word segmentation handles Unicode letters, Arabic punctuation/diacritics and
CJK characters. Pronoun-specific opening hints cover English and Russian. Short
action phrases use limited English, Russian and Arabic form heuristics; longer
exact phrases have broader script coverage. These lightweight rules are not a
morphological parser and do not certify equivalent behavior in every language.
Quoted or deliberately repetitive styles may be under-detected; a repeated
unquoted passage can still be intentional.

## Prompt and state boundary

`flow_guidance` emits at most 1,200 characters of fixed category advice, only
after a budget is exceeded. It copies no source phrase, actor name or story
excerpt into its report or prompt. Off returns before analysis. With no pattern,
the existing prompt remains unchanged.

The shared narration assembler appends the bounded advice after the stable system
prefix. The same resulting prompt reaches streaming, buffered character rendering
and its existing repair/fallback. Regeneration uses the same narrator settings
and eligibility adapter with its already loaded history. No query is added to
assemble a second history, and style metrics cannot request a retry.

Advice explicitly asks to preserve character distinctions, purposeful repetition, quoted dialogue,
callbacks, player agency, required formatting and exact consequential numbers.
It remains subordinate to selected literary voice, amount, pacing and compatible
editorial corrections. It does not choose a voice for audio playback or enforce
an automatic rewrite of quantities. Separate constrained combat-aftermath and
terminal-report tasks, translation, and mechanics extraction remain unchanged.

## Reproducible offline comparison

Run `python scripts/evaluate_narration_flow.py --profile gentle` (or `balanced` /
`off`) to compare the checked-in fictional examples. This command needs no model
configuration, database or API key. Its JSON contains metrics and editorial review
notes, with no source prose. Fixtures cover English, Russian, Arabic, Japanese,
Chinese and Korean.

The examples were authored for detector validation. They are not model outputs
and are not a benchmark showing that generated prose became better. Candidate
versions remove repeated ornamental beats while retaining the number 72 and the
same speaker-tagged dialogue. Review still needs to check meaning, the timing of
revealed facts, distinct voices, readability and world continuity. A smaller count
alone is not a quality score.

For the checked-in examples with Gentle, the maximum support for a repeated
phrase changes as follows. Each baseline has four prose-containing replies;
each candidate has one such reply followed by three dialogue-only beats, which
are intentionally excluded from narrator-habit measurements.

| Language | Phrase support, baseline → candidate | Detected categories, baseline → candidate |
| --- | --- | --- |
| English | 4 → 1 | phrases, openings, closings → none |
| Russian | 4 → 1 | phrases, openings, closings → none |
| Arabic | 4 → 1 | phrases, openings, closings → none |
| Japanese | 4 → 1 | phrases, openings, closings → none |
| Chinese | 4 → 1 | phrases, openings, closings → none |
| Korean | 4 → 1 | phrases, openings, closings → none |

The editorial notes retain Sana's questions, Rowan's confirmation, the map,
lantern and exact reading. Removing repeated ornamental beats changes the
presentation; it does not demonstrate that a model will make the same edit or
that every omitted gesture is irrelevant in another story.

Before a live comparison, hold the world, narrator voice, amount, scene pacing and
model settings constant. Compare Off with an enabled profile over a long enough
window; include deliberate callbacks and dialogue-heavy passages. Record the
metrics alongside an editorial review, including false positives and missed
patterns. The engine does not automatically make extra comparison requests.
