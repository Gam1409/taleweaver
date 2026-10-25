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

Vectors are stored in **`db/lancedb/` at the project root**, ignored by Git.
`MEMORY_DB_DIR` can override that directory. Docker mounts the project `db/`
directory at `/app/db`. Canonical history remains in the existing application
database; back it up along with the usual session data.

## What is remembered

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

## Turn latency and recall

A turn computes one shared recall result for narration, VN continuity and social
reasoning. Retrieval combines vector similarity with lexical relevance, importance
and recency, then validates results against current SQL sources. Owner, session,
timeline generation and model signature isolate the index. Old clothing and
possession descriptions are historical evidence; current game state wins.

Foreground recall has a short vector deadline and falls back to SQL-based lexical
selection when the embedding service fails or indexing is incomplete. It never
waits for the backlog to be indexed or summarized. Context is bounded to 2,500
characters and filtered for the receiving pass. Disabling recall retains the
legacy memory context.

Journal extraction, index batches and summaries share an idle scheduler. A new
background unit starts only after a 15-second quiet period; a foreground turn
prevents additional units from starting. Summary calls use the configured
**compression** role, with bounded input and a 30-second deadline. Failed work
backs off; subsequent session activity can restart it. Very slow models can time
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

Changing embedding settings invalidates the old vector space; background work
rebuilds it without mixing dimensions or model signatures. Explicitly paused
indexes stay paused. Rewind invalidates future-derived memory, and session
copy/import remaps source message references. Session deletion cleans up its
index; deleting a template preserves surviving sessions and their history.

For diagnostics, `gm.turn.memory_recall` records retrieval method, selected source
IDs/layers, elapsed time and context length without logging embedding credentials
or raw memory text.
