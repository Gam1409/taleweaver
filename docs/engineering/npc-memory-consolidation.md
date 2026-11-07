# NPC memory consolidation: assessment and first implementation wave

## Decision

Periodic, source-linked consolidation is useful for long RP sessions. Reuse the existing NPC fact extraction and RAG summary worker; do not add a second background summarizer or replace accepted psychological history with model prose. A summary reduces recall input, not the size of the complete audit archive.

The implemented NPC-summary cadence is approximately 20 completed source replies that established facts involving a given NPC, with earlier bounded processing when the input character budget fills. This counts relevant source replies, not all turns in a twenty-character adventure, and not the number of facts extracted from one unusually busy reply. Failed or interrupted responses do not qualify. Work uses the existing idle scheduler and RAG settings, never a new blocking phase before every RP response. Ordinary story/scene summary thresholds are unchanged.

## What is already implemented

| Component | Existing behavior | Remaining cost or limit |
| --- | --- | --- |
| Public character journal | Extracted facts with source message, scene, topic, category, significance and claimed/observed attribution. New replies carry a separate game-clock recording stamp. Ephemeral observations and repeated unchanged facts are filtered. | Legacy game dates stay unknown. Appending and several readers still expand the full archive. |
| Journal archive | Lossless compressed chunks of 128 records; mutable tail of at most 256 entries. Save copying, import and rewind preserve provenance. | Compressed chunks remain inside NPC metadata; total bytes and complete-archive processing still grow. This is storage compression, not semantic consolidation. |
| Public RAG summaries | Existing NPC/scene/story summaries, source hashes and fragment coverage; bounded idle jobs (up to 12,000 input characters, 24 source messages and a requested 250-word summary). NPC jobs now normally wait for 20 relevant replies; story/scene jobs retain their eight-message minimum. | Summary text is derived historical information, not authoritative current state. Dense sources can trigger earlier fragment jobs. |
| RAG recall | Session/owner/generation filters, semantic and lexical retrieval, scene/NPC anchors, significance weighting and a bounded latest-topic working set. | Candidate loading can still expand complete journal archives. More similar events make scope, time and stable identities increasingly important. |
| CHPM private memory | Observer-scoped evidence, exact sources, lexical/optional semantic recall, separate active agenda and causal links. Active event archive rolls over without deleting evidence. | The exact ledger remains finite: 8,192 events/sources and 2,048 beliefs per NPC. Consolidating prompt text alone does not remove these limits or replay cost. |
| Living World journal | Bounded pending and completed events, causal prerequisites and explicit request budgets. | Its 512-event journal and timeline-wide deliberation budget are separate limits. Neither public RAG summaries nor compressed NPC metadata resolve them. |

References: [journal archive](../../backend/engine/npc_journal/archive.py), [fact records](../../backend/engine/npc_journal/records.py), [summary worker](../../backend/engine/memory_rag/summaries.py), [foreground source loading](../../backend/engine/memory_rag/recall_sources.py), [working set](../../backend/engine/memory_rag/core.py), [CHPM capacity](../../backend/engine/chpm/capacity.py), [Living World contracts](../../backend/engine/living_world/schema.py).

## Useful metadata

Prefer canonical fields over a growing bag of free-form labels:

- owner, adventure/session, branch and observer scope;
- actor and other established participant IDs;
- scene ID and exact source message/revision/hash;
- game minute at recording, separate from inferred event onset and wall-clock recording time;
- stable topic or object ID, category and significance;
- epistemic status: witnessed, heard/reported, belief or unresolved interpretation;
- explicitly supported links to an event, active goal, condition or consequence;
- temporal status where actually established: historical, current, superseded or explicitly resolved.

Do not infer these fields just to fill a schema. A missing game timestamp stays unknown. A shared source message does not prove causality. An NPC's absence does not prove that a condition resolved. A model-generated keyword must never grant access to another NPC's private memory.

Tags should identify and constrain retrieval before they add ranking weight. Owner/session/observer filters are mandatory. Scene and time are relevance cues rather than universal hard filters: a clue from another room or a promise from last month can be exactly what matters now. Current host state and active commitments receive their own bounded projection. Historical material competes by lexical/semantic relevance with scene, actor, topic and time as additional cues. Similar wording alone must not merge events from different episodes.

## Consolidation contract

Keep recent exact observations, a compact source-linked account of an older interval, and the retrievable original archive as separate layers. Do not repeatedly summarize only the previous summary: regenerate from canonical facts/source fragments so omissions do not become permanent facts of a new chain of summaries.

An interval should retain established events, open commitments, changed conditions, decisions, explicit causes and consequences, contradictions and uncertainty. Later completion or withdrawal must remain distinguishable from the original promise. The current agenda and physical/item state retain authority; a summary does not close goals, heal wounds, clean clothing or revise personality.

Two attribution boundaries matter: the public character journal records information learned in the player's story, while CHPM private memory contains only that observer's admitted evidence. Public summaries must not automatically become another NPC's personal memories. Use the existing observer namespace and source validation for any future private consolidation.

On a failed, stale or invalid consolidation, keep the previous usable view and all original records. Rewind, edited narration and session copying must invalidate or remap summaries and their time/source bindings. A retrieved summary and its raw source are one evidence lineage, never independent confirmations.

## Work order and acceptance checks

1. **Implemented:** stamp the game clock at reply persistence. Carry it through deferred learning, retry, copy/import and replay. The later background worker's current session clock does not date an older event. Legacy/invalid dates remain absent; zero is a valid game minute.
2. **Implemented:** extend the existing NPC summary job with the relevant-reply cadence and explicit chronological source metadata. Source rows include canonical scene/NPC IDs, topic, significance, epistemic provenance, recording dates and known game minutes. Preserve the earlier size-bound path for unusually dense replies and existing fragment coverage. Fragmentation now leaves metadata headroom and accounts for JSON escaping so a near-limit source cannot block progress.
3. Measure and remove full cold-archive expansion from hot-path recall. Keep full source inspection available for background indexing, explicit history pages and save operations. Design the derived working projection and its invalidation before caching it.
4. Address exact archive storage separately. Moving cold records out of repeatedly rewritten NPC/session JSON needs a portable archive, ownership rules, migration, export/import and replay tests. Do not call deletion or higher caps “consolidation.”

Required fixtures include 20/200/2,000 relevant turns; similar events in different rooms; two NPCs with different knowledge; old unresolved goals amid routine chatter; changed and reversed facts; a dense single turn; an edited or removed source; a multi-month time jump; delayed learning; empty and malformed model output. Measure source coverage, wrong-episode retrieval, lost active commitments, bytes loaded, selection time, actual prompt size and model calls. Offline tests can establish these contracts; semantic faithfulness and psychological quality still require live model evaluation.

The first two steps reuse the existing worker and model connection. They do not add a model phase to foreground RP. A normal NPC summary job is amortized over approximately 20 relevant replies; dense fragments and existing retry behavior can change that count. Exact token cost depends on the configured tokenizer and source lengths. The 12,000-character summary-input ceiling and 2,500-character shared foreground recall ceiling remain in place, including metadata.

Known game minutes are canonical document/projection metadata. This wave does not add a LanceDB time-range index, new arbitrary tag fields or a private semantic-summary store. Existing owner/session/observer isolation and scene/NPC relevance remain in force. Fragment source hashes now include their actual text, so changing fragment boundaries cannot incorrectly reuse an older embedding.

Regression fixtures cover 20/200/2,000-source inputs, multiple scenes with identical event text, a separate NPC, zero and unknown game minutes, delayed learning after a three-day clock advance, claim/defer/failure/dependent-retry handling, original-message remapping and JSON budget edges. These are host/source-contract checks with mocked model calls, not proof that a real model's summary preserves every psychological nuance.

Steps three and four remain architectural work. Removing finite CHPM limits and moving archival storage have different correctness contracts; they should not be hidden inside a prompt-tuning patch. See the [80-scenario matrix](rp-adversarial-scenario-matrix.md) for the wider evaluation backlog.
