# Optional bounded CHPM agent

The existing flow remains the default (`agent_steps=0`). In session settings →
NPC behavior → Enabled → Agent lookups per active NPC, select one or two rounds.
The setting belongs to the saved game session, not the adventure template or user.
The existing Small/Complex role routes these calls; no separate endpoint is required.

## Execution

Perception → reconcile this observer's sources → optional lookup rounds → existing
source-grounded proposal and intent selection → narration → review/repair → commit.
Each round asks the model for zero to two allowlisted read requests. An empty list
ends investigation early. The next round can refine a search or read a returned
source. At the step limit, the decision uses the evidence actually obtained;
missing information remains unknown. There is no open-ended planning loop, browser,
shell, arbitrary SQL, state-edit tool, or automatic retry of malformed agent JSON.

Available tools:

| Tool | Input | Scope/result |
| --- | --- | --- |
| `search_memory` | concrete query, up to 160 characters | Existing RAG ranker over this NPC's reconciled speech/world observations from prior turns, including archived sources; at most two hits |
| `read_memory` | ID returned earlier in this investigation | Original observed excerpt, at most 2,000 characters; never the entire original chat message |
| `inspect_self` | empty argument | Current host frame: own location, owned item names/IDs and worn IDs; unknowns and omissions remain explicit |
| `visible_clothing` | present NPC ID | Session-resolved clothing projected by opaque layers and uncovered regions, with layer number and visible regions |
| `inspect_beliefs` | subject actor ID | Up to two recent own beliefs about that person, marked tentative/challenged and subjective; never that person's private thoughts |
| `read_belief_basis` | belief ID returned by inspection in this investigation | Up to two recent interpretations, each with up to two exact source quotes, preserving support/challenge of the proposition |

Search is **lexical**, not embedding-based. The model can supply alternate cues,
but a miss does not establish that an event never occurred. The session-wide RAG
index, global summaries, private thoughts, and other NPCs' inventories are not
exposed. There is no certified NPC audience ACL on those broader sources yet.
Reusing the RAG ranker does not grant access to its global document collector.

Belief inspection pins at most two propositions across the entire investigation.
Their handles remain available in the proposal's belief and motive allowlists even
when ordinary historical context packing would omit them. A stale/retracted belief
cannot be read using an old handle. Evidence reads share the existing 6,000-character
source budget; each citation is at most 300 characters, with explicit omission counts
or unavailable/budget statuses. They do not revise beliefs themselves. Only the
validated proposal may propose a revision, and only a reviewed turn commits it.
Supporting/challenging a proposition never means approving/disapproving its subject.
Retrieved quotes reach narration/review with report/witness provenance; subjective
belief statements are not manufactured into observed world facts.

The agent receives the reserved `player_actor_id=@player` and up to 32 recent
`belief_subject_ids`, with an explicit omitted count. IDs identify read subjects;
they do not establish presence, reliability or another person's knowledge. The
agent-stage state view does not point to the later, absent appraisal-context block.
An unknown/self subject returns `unavailable_subject`; a known subject with no
ordinary beliefs returns a legitimate empty `ok` result. Names are not guessed or
converted to IDs. Both the subject view and reads remain observer/session-local.

Visible clothing uses canonical object metadata, session overrides, the existing
clothing-detail setting and explicit age rules. Covered lower layers and carried
items are excluded. Missing profiles/references remain unknown. Co-presence uses
the existing scene visibility/presence rules; this is not a geometric line-of-sight
simulation. A visible-clothing read becomes a source-bound observation at this turn,
not proof of a change, transfer, desire, or consent. Older clothing observations
remain historical; current host facts take precedence.

## Limits and safety of state

- `agent_steps`: 0–2; only Enabled/live mode uses the loop.
- Each round: one logical model call, at most 768 output tokens (also limited by
  the selected role and the saved CHPM output budget), up to two local reads.
- Pinned source excerpts: at most eight distinct sources and 6,000 characters per
  NPC, shared by search, belief-basis, self and clothing reads. A ninth source
  returns `evidence_source_limit_reached` without evicting earlier reads. Expanding
  an existing handle remains possible within the character budget. A partially
  available search/basis response reports `partial`; the proposal receives that
  status and the audit retains individual refusal reasons. Canonical history is
  never removed to fit the tool view.
- All planner/proposal inputs obey the configured character limit. Existing
  historical-view packing may reduce optional old context, never pinned reads.
  For fuller lookups, 32,000 input characters is a practical starting setting;
  this is not a measured latency guarantee. Saved budgets are never raised silently.
- Admission reserves `active NPCs × (1 + agent_steps) + 5` CHPM calls in live mode.
  This includes perception, a shared proposal retry, review, and a repair/review
  pair. The ordinary narrator call remains separate. For three active NPCs and
  two agent rounds, reserve **14 CHPM calls**, versus 8 without the agent.
- The host checks session/observer ownership, source handles, current frame, and
  present-actor access. Tools read only the current turn's captured clothing views.
- Psychological updates, looked-up clothing observations and audit records commit
  only with the successfully reviewed reply. Failure leaves saved state unchanged.
  Rewind/regeneration invalidate their source-bound causal history as before.
- Tool exposure, source handoff and persisted decisions use the same source bounds.
  The complete decision is validated after handoff. Save validates serialized state
  before replacing session JSON, including nested models mutated after construction.
  An invalid update leaves the previous state and revision unchanged. These checks
  use no model requests and do not increase limits or alter the saved-state schema.
- `Decision.agent_audit` records short purposes, requests, result statuses, original
  source/message IDs, and stop reason. Full model deliberation is not requested.
  A long optional purpose label is shortened to 180 characters with an explicit
  truncation flag; cosmetic verbosity cannot reject valid tool requests.
  This trace is exposed through the existing administrator-only endpoint.

Host envelope version 6 migrates versions 1–5, retaining budgets and state, with
agent lookups defaulting to off. The core snapshot is independently versioned.

### Cost of the two belief tools

Local measurement against `bc33c1e6` (2026-11-05), using production prompt/schema
serialization: the planner instructions and schema grow from 1,920 to 2,227 Unicode
characters, **+307 per invoked round**. Roughly 80–110 English tokens is a planning
estimate, not an Artemis tokenizer measurement. The split-belief proposal instruction
and schema together grow by only 13 characters after removing redundant wording.
No extra round, request allowance, output budget or endpoint is added.

One fixture with a challenged promise returned 192 characters from inspection and
758 from basis lookup; 37 exact source characters were pinned. These are fixture
measurements, not a worst-case guarantee. Actual input usage depends on returned
beliefs/sources and later handoff. Choosing an available round instead of stopping
early still costs a model call. All existing input limits remain enforced.

## Local validation and pending live work

Local tests cover search/read, original source IDs, old memory, unavailable/foreign
handles, session isolation, clothing occlusion/displacement, unknown/stale views,
canonical/session clothing data, request admission, early stop, step limits,
malformed JSON/timeouts, successful VN commit and rollback after rejected prose.

The belief tools and split-belief wire schema have only local mock coverage.
Earlier Artemis live runs exercised memory/clothing reads and source handoff, but
do not validate these new additions. No claim of improved psychological fidelity,
recall quality or speed can be made from mocked tests.
A short controlled comparison must use the same scenes with agent off/on: exact
and paraphrased recall, revised old facts, dense short speech/actions, visible
clothing changes, multi-session isolation, and two active NPCs. Evaluate semantic
errors and unnecessary questions, not just JSON validity or agreement with the player.

The matrix CLI supports `--agent-steps 0|1|2` and `--input-chars`. Plan without any
network calls first, for example:

```bash
python -m backend.engine.chpm.evaluation.matrix_cli plan --suite stress \
  --case recall-paraphrase-h40 --agent-steps 2 --input-chars 32000 --output-tokens 4096
```

Use the same input/output budgets for the agent-off comparison. `run` still
requires an explicit endpoint/user, run ID and total call quota. The matrix's
synthetic fixtures have no live wardrobe database, so visible clothing must also
be tested in a saved VN session; the tool reports unavailable there rather than
inventing a fixture wardrobe. Manifest v5 records the agent and input overrides.

Retrieved excerpts also reach the narrator and reviewer as `agent_observed_sources`,
independently of which motives the model selects. IDs, provenance, exact text,
historical/current status and report/witness distinction are retained. The host
rechecks these excerpts against the same observer's saved sources before rendering;
missing/retracted/altered sources fail visibly. A model reviewer can still miss
semantic contradictions; this handoff fixes missing input, not model infallibility.


A completed but malformed optional lookup plan (invalid enum, oversized argument,
excess request count, invalid JSON or exhausted output) is skipped as one whole
batch. No partial plan executes. `agent_audit.stop=invalid_plan` and
`lookup_performed=false` record the degradation; the subsequent proposal receives
`agent_plan_status`. This is not a zero-hit memory search and authorizes no invented
knowledge. Transport errors and session-scope violations still stop the turn; no
transport retry was added.
