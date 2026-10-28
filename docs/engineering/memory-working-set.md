# Bounded memory working set

Memory storage and model context have separate limits. The SQL transcript and NPC journals remain complete; enabling RAG does not replay the complete archive on every turn.

## Turn context

The configured `max_memory_turns` now controls complete user-led exchanges, including their assistant replies and system messages. The chronicle uses the same boundary. A fixed twelve-message limit no longer silently removes recent exchanges from the main turn pipeline.

RAG retains its shared 2,500-character ceiling, including metadata and instructions. Latest known topics for present NPCs receive a round-robin share of the existing facts budget; this does not add another growing prompt block. Other relevant historical records can still be retrieved. Recording dates are explicitly distinguished from in-game time, and remembered claims cannot override current possessions, clothing or location.

An empty recall preserves the legacy context path. When lexical search finds no match, canonical session notes and the chronicle remain eligible for a bounded projection. Retrieval queries can include the last two messages for conversational context. Important significance labels contribute to ranking, independently of the language of the prose.

NPC extraction also has a shared 12,000-character cap for known-character context. Present or explicitly mentioned characters are prioritized, with compact identities for other characters. This is a character-context ceiling, not the total LLM request limit.

## Maintenance and summaries

Chronicle compression and grouped summaries run before optional embedding indexing. An unavailable embedder therefore cannot prevent an eligible canonical summary from being attempted. Within indexing, learned facts and summaries precede raw dialogue. Model calls retain the configured role/provider deadlines.

Summaries track exact `source_keys`, in addition to their message IDs and evidence hash. Long messages are processed as bounded fragments across separate jobs, including a short final fragment. Legacy rows with null keys retain whole-message coverage. Import/copy remaps fragment message identifiers; editing or deleting source fragments invalidates derived summaries. New summaries use the session language rather than unconditional English.

Migration `8f4c2a9d10be` adds one nullable JSON column to `memory_summaries`. It does not delete journals, messages, summaries or vectors. Normal backend startup runs migrations. Existing summaries are not rewritten solely to change language.

## Learning status and retries

The character directory distinguishes queued work, extraction, waiting to save, saving and recovery. A model may finish while a foreground turn still owns the writer: that wait is displayed explicitly. Completed processing can legitimately add no facts; routine gestures and repeated information remain excluded.

Retryable and expired work has a process-owned wakeup timer, so retries no longer require keeping the directory open. Attempt limits, cooldowns, ownership checks and fencing remain active. Restart recovery still uses durable SQL task state when the session is loaded.

System diagnostics include safe learning phases, retrieval method and audience. They do not include story text, prompts or character facts.

## Deliberate limits of this change

- LanceDB remains an optional derived index; no replacement database or additional LLM service is required.
- The full transcript is still indexable. Event-selective archival indexing is a separate policy change.
- A latest-topic projection is not a full temporal knowledge graph or per-character knowledge ACL.
- The background scheduler remains process-local and waits for foreground transactions. This change makes that wait observable; it does not remove SQLite fencing or guarantee immediate completion on a shared GPU.
- Prompt budgets remain character-based. Tokenizer-aware budgets and per-mode memory selection need separate measured evaluation.

Regression coverage includes long-message tail coverage, fragment import and invalidation, old-schema migration, complete-turn windows, multiple-NPC projection, empty-recall fallback, retry wakeups and UI state changes. Model traffic is mocked in automated tests; semantic extraction quality still depends on the configured model.
