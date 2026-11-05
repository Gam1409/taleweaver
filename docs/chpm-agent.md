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
| `search_memory` | concrete query, up to 160 characters | Existing RAG ranker over this NPC's reconciled speech/world observations, including archived sources; at most two hits |
| `read_memory` | ID returned earlier in this investigation | Original observed excerpt, at most 2,000 characters; never the entire original chat message |
| `inspect_self` | empty argument | Current host frame: own location, owned item names/IDs and worn IDs; unknowns and omissions remain explicit |
| `visible_clothing` | present NPC ID | Session-resolved clothing projected by opaque layers and uncovered regions, with layer number and visible regions |

Search is **lexical**, not embedding-based. The model can supply alternate cues,
but a miss does not establish that an event never occurred. The session-wide RAG
index, global summaries, private thoughts, and other NPCs' inventories are not
exposed. There is no certified NPC audience ACL on those broader sources yet.
Reusing the RAG ranker does not grant access to its global document collector.

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
- Pinned source excerpts: at most 6,000 characters per NPC. Exceeding this returns
  an explicit tool status; sources are not silently discarded to make room.
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
- `Decision.agent_audit` records short purposes, requests, result statuses, original
  source/message IDs, and stop reason. Full model deliberation is not requested.
  This trace is exposed through the existing administrator-only endpoint.

Host envelope version 3 migrates versions 1/2, retaining budgets and state, with
agent lookups defaulting to off. The core snapshot is independently versioned.

## Local validation and pending live work

Local tests cover search/read, original source IDs, old memory, unavailable/foreign
handles, session isolation, clothing occlusion/displacement, unknown/stale views,
canonical/session clothing data, request admission, early stop, step limits,
malformed JSON/timeouts, successful VN commit and rollback after rejected prose.

The stopped Artemis live run predates this implementation. No claim of improved
psychological fidelity, recall quality or speed can be made from mocked tests.
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
