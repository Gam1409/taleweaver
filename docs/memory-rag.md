# Memory and relevant recall

TaleWeaver keeps game state and history in its existing SQL database. Optional
LanceDB indexing adds retrieval of older, relevant events; it does not replace
inventory, clothing, relationships or the session checkpoint system.

## Setup

1. Install the updated dependencies and apply migrations with the normal setup
   procedure: `./setup.ps1 -SkipStart` on Windows or `bash setup.sh --skip-start`
   on Linux/macOS. Both install LanceDB through Poetry and verify its import
   before migrations. Manual setup: `poetry install`, then
   `poetry run alembic upgrade head`.
2. Open **Admin → Memory & recall** below the model settings.
3. Choose **OpenAI compatible** or **Ollama**, enter an embeddings URL and the
   exact name of an installed **embedding model**, then use **Test embeddings**.
   A chat/completion endpoint alone is insufficient. OpenAI-compatible servers
   must implement `/v1/embeddings`; Ollama must implement `/api/embed`.
4. Enable memory recall and save. Indexing starts automatically in idle time.
   The optional API key is encrypted through the existing credentials vault.
   Leaving its input empty preserves the stored key.

These are shared administrator settings, like the existing LLM configuration.
An embeddings model may run on a separate server from the narrative models.
Use a multilingual embedding model when the story and player input use different
languages. A successful endpoint test verifies the response format, not recall
quality for a particular language or story.

In **Advanced embedding instructions**, set query and document prefixes exactly as
the embedding model requires. For Snowflake Arctic Embed 2.0, use `query: `
(including the final space) for queries and an empty document prefix. Other models
can require different instructions. Empty prefixes preserve the existing behavior.
Prefix changes invalidate the previous vector space and schedule rebuilding.

Vectors are stored in **`db/lancedb/` at the project root**, ignored by Git.
`MEMORY_DB_DIR` can override that directory. Docker mounts the project `db/`
directory at `/app/db`. Canonical history remains in the existing application
database; back it up along with the usual session data.

## What is remembered

Foreground journal recall reads the mutable tail first. Cold compressed blocks
carry derived, content-checked source indexes; an old vector hit expands only its
matching blocks. Missing or stale indexes fall back to canonical decoding.
Bounded prompt context stops once its existing character budget is filled.
Export, copy and inspection retain every canonical record. Cold JSON storage and
full background scans still grow with history; this optimization does not remove
the finite exact archive limits or replace consolidation.

New NPC journal extraction prioritizes durable facts, promises, boundaries,
decisions, consequences, relationship changes and stable appearance changes.
It requires an explanation of the change and evidence from the narration.
An empty extraction is valid. Routine movements, glances, repeated descriptions
and restatements of known facts should not create entries. The live extraction
boundary rejects unclassified or explicitly ephemeral observations; deduplication
also rejects normalized repetitions of the same fact. Genuine reversals and
the difference between a claim and an observation are preserved.

This is a semantic task for the utility model. Code validates the classification
and evidence, but cannot guarantee that a weak model correctly labels every
detail. Existing journals are kept intact, including legacy entries.

The index contains public, source-backed NPC facts, world memories, session notes,
dialogue and historical summaries. Private NPC inventories and thoughts are not
added as public memories. Longer text is split into overlapping chunks. Summaries
are grouped into NPC, scene and story intervals with references to their source
messages; old intervals remain available instead of being replaced by only the
latest summary. Large source groups that cannot fit a summary request remain
searchable as raw chunks.

When explicitly enabled for NPC Personality, a separate **observer** namespace
indexes that NPC's saved observations. Public recall cannot query these rows;
one NPC cannot retrieve another NPC's observations. This is distinct from shared
narration recall. See [semantic NPC memory](chpm-semantic-memory.md).

## Turn latency and recall

A turn computes one shared recall result for narration, VN continuity and social
reasoning. Retrieval combines vector similarity with lexical relevance, importance
and recency, then validates results against current SQL sources. Owner, session,
timeline generation and model signature isolate the index. Old clothing and
possession descriptions are historical evidence; current game state wins.

Foreground recall uses the configured embedding request timeout (30 seconds for new
settings, adjustable from 1 to 60 seconds) and 0.5 seconds of additional vector-search
grace, then falls back to SQL-based lexical selection when the embedding service fails
or indexing is incomplete. Explicit saved timeouts are preserved; increase the value
in Memory & RAG settings if an existing installation still has 10 seconds. Changing
only the timeout does not rebuild the index. A larger timeout can lengthen turns when
the server is busy. Recall never
waits for the backlog to be indexed or summarized. Context is bounded to 2,500
characters and filtered for the receiving pass. Disabling recall retains the
legacy memory context.

The final context preserves scene and message references. Repeated wording in
different episodes remains distinct; only duplicate instances of the same source
are folded. Query-focused excerpts retain exact document offsets instead of always
taking the beginning of a match. Unused category space can be borrowed within the
same total limit, so a large cast cannot reduce every record below the minimum
size. A completely unrepresentable result preserves the legacy memory context.
Scene/cast changes refresh canonical SQL selection and ranking in the same turn,
while reusing that turn's original vector lookup.

Journal extraction, index batches and summaries share an idle scheduler. A new
background unit starts only after a 15-second quiet period; a foreground turn
prevents additional units from starting. Summary calls use the configured
**compression** role, with bounded input and that role's configured deadline.
Public indexing, chronicle compression, interval summaries and optional observer
indexing take turns, with at most
one model batch per idle unit. A failed phase backs off independently, allowing
other phases to advance; subsequent session activity can restart deferred work.
Very slow models can time
out during summarization while raw history remains available for retrieval.

This is process-local scheduling, not remote inference preemption. A request
already executing on a single-slot model server may still delay the next turn,
and stopping the local await does not guarantee that the remote server stops
generating. Separate embedding/utility capacity helps avoid that contention.

## Clear, rebuild and saved sessions

In the adventure card or library table menu, open **Memory index**. Clearing
removes that owner's vectors for the adventure and its sessions, preserving
dialogue, NPC history, summaries and game progress. It pauses indexing for those
sessions so the next turn does not immediately recreate the cleared vectors.
Use **Rebuild index** to resume and rebuild from canonical history.
Clear/rebuild also covers observer vectors; canonical NPC psychology remains in
the session save.

Changing embedding settings invalidates the old vector space; background work
rebuilds it without mixing dimensions or model signatures. Explicitly paused
indexes stay paused. Rewind invalidates future-derived memory, and session
copy/import remaps source message references. Session deletion cleans up its
index; deleting a template preserves surviving sessions and their history.

Checkpoints store revision IDs and content hashes only for narration sources
referenced by their saved NPC journals, including archived entries and observed
descriptions. Restoring a checkpoint keeps retained narration revisions and
retracts evidence whose source changed or disappeared. Existing journal tasks
return to the ordinary background queue; restoration makes no model request.
Older checkpoints without these anchors retain matching evidence and validate
available quotations against the current session-local assistant reply. Legacy
records without quotations cannot establish a historical revision and retain
their previous treatment. Private cognition continues to validate its own saved
source revisions and hashes before live use. Authored and manually edited NPC
descriptions remain independent of observed description provenance.

For diagnostics, `gm.turn.memory_recall` records retrieval method, selected source
IDs/layers, elapsed time and context length without logging embedding credentials
or raw memory text.

## Session World Info

[World Info](session-world-info.md) adds reviewed, source-attributed reference knowledge
to an individual session. Uploads and edits remain separate from adventure templates,
canonical gameplay state and NPC observations. Its guide describes processing, audience
scopes, publication, replacement, copying and checkpoint behavior.
