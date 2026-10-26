# Persistence and concurrency audit

This audit follows a reported `database is locked` failure while saving an NPC
journal extraction. It covers RAG maintenance, visual persistence, settings and
session mutation paths. It does not establish that every possible race is absent.

## Changes

- Background persistence waits for active foreground turns outside SQL sessions.
  SQLite contention retries open fresh transactions and revalidate sources and
  claim tokens. Successful model output is reused during persistence retries.
- NPC journals, summaries, chronicles, vector batches and worker lease updates use
  this persistence boundary. Claim expiry allows takeover; an actual token or
  epoch change prevents an old worker from writing.
- Index creation uses conflict-safe insertion. Reset/rebuild epochs and queued
  revisions increment atomically instead of copying stale ORM values.
- Native LanceDB mutations finish before cancellation releases their SQL fence.
  Read-only vector queries remain cancellable. A mutation timeout may therefore
  exceed its nominal duration while native cleanup completes.
- Portraits, illustration attachments and scene backgrounds preserve concurrent
  state changes. Template regeneration releases its transaction before inference
  and rejects attachment after a conflicting edit or deletion.
- Settings saves broadcast only the edited columns. Shared LLM, embedding and
  credential JSON is reread under a short write fence before merging.
- Session mutations share the streamed-turn lease. Chat polling during a turn is
  read-only and does not create maps, advance sequences or persist suggestions.
- Legacy template-scoped mutations pin the selected session. Reset locks captured
  sessions, purges derived memory and deletes their dependent data; sessions
  created after selection are not swept into that reset.

## Validation and limits

The final combined regression run passed **522 tests**.

Regression tests cover real competing SQLite writers, rollback after partial
writes, unchanged model call counts, edited/deleted sources, claim takeover,
concurrent JSON updates, native storage cancellation, reset cleanup and read-only
polling. Model responses are mocked; these tests verify persistence behavior, not
live provider quality or throughput.

The broader adventure API suite has 16 existing failures caused by outdated-format
session-start fixtures. The same failures reproduce on unchanged commit
`9ac6dfef`. The legacy `sessions.py` module also has pre-existing lint/format
findings; forwarding four endpoints to the new helper introduces no new Ruff
findings. New modules and the other changed Python files pass Ruff checks.

The main turn still flushes state before awaiting remote inference and commits at
its end. Different sessions can consequently compete for SQLite's single writer.
Solving this fully requires staging inference separately and revalidating changes
in a short final transaction; inserting arbitrary intermediate commits would
break rollback semantics. Session leases are process-local, matching the standard
single-worker launcher, and are not a multi-process locking guarantee.

A rejected stale image generation can leave an unreferenced output file. The
current changes protect canonical state; automatic orphan-file collection is a
separate concern.
