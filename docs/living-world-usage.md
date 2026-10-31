# Living World rules preview

Branch: `experiment/living-world-concordia`. This is the persistence and rules
vertical slice, not the complete autonomous-NPC specification. It does not generate
goals or conversations, call an LLM, or install Concordia.

## Try it

1. Back up the local database and session exports before switching branches.
2. Install the usual dependencies and run `poetry run alembic upgrade head`.
   Normal backend startup also applies migrations.
3. Start the usual single-worker backend and frontend. Open a test session's
   settings and **Living World · Experimental**. Enable and save.
4. **Pause while away** preserves game time. **Catch up when returning** converts
   absence into a pending target. Leave the session, return, then refresh status.
5. **Continue catch-up** processes one bounded batch: by default six game hours,
   sixteen events and two wall-clock seconds. Unprocessed time remains available.
   Automatic resume runs only one batch per reconnection, not an endless loop.

An empty queue advances only the clock. Administrators explicitly schedule rule
events through the API in this preview. Enabling the feature alone does not make
NPCs autonomous or change narration prompts.

Presence runs independently of inference. Closing or leaving the session ends
presence; switching tabs or waiting for an LLM does not. A crashed browser has a
60-second heartbeat grace period. Browser suspension/network loss can approximate
absence rather than detect it precisely. Multiple live tabs prevent double counting.
The clock uses server UTC, not the browser timezone.

## Recovery and privacy

- **Stop after current event** stops between atomic commits. Continue resumes from
  the committed cursor. Zero budgets intentionally make no progress.
- Pending catch-up blocks a new normal turn while enabled. Finish the batch or
  disable the experiment to play normally; disabling retains the queue and target.
  Changing time mode requires finishing the pending target.
- DECISION/SOCIAL enter **WAITING_FOR_LLM** without invented outcomes. There is no
  adapter to resolve them yet: disable the experiment or restore a checkpoint to
  play without the pending simulation.
- After a crash, committed events survive. A stale RUNNING state is displayed as
  PARTIAL when no local runner exists and can be resumed.
- Chronicles/full-turn rewind restore the queue and fork its timeline identity.
  Copy/import also fork the timeline and discard browser presence. Deletion uses
  existing session cascades; there are no separate simulation files.
- Keep SQL on persistent local storage. GPU shutdown does not affect this preview.
  Exports contain the private queue for restoration: treat backups as private, not
  as player recaps. This feature creates no new LanceDB index.

## API and mechanical demonstration

Base: `/api/adventures/{session_id}/living-world`. All requests require the existing
authenticated owner; event inspection/scheduling also require the administrator role.

| Request | Purpose |
| --- | --- |
| GET base | Public settings/status without private event details |
| PATCH base | `{settings, expected_revision}`; stale revisions return 409 |
| POST `/presence` | `{client_id, active}`; conditional independent update |
| POST `/resume` | `{expected_revision}`; one bounded batch |
| POST `/stop` | Stop between events |
| GET `/events` | Private administrator journal |
| POST `/events` | Unexecuted proposal; duplicate IDs return 409 |

In a test world with movable LILI/MIRINDA and an unlocked START -> ROOM exit,
POST each object separately. Replace IDs with actual session-owned IDs and use
absolute game minutes at or after the cursor:

```json
[
  {"event_id":"lili-move","due":60,"kind":"MOVE","actor":"LILI","destination":"ROOM"},
  {"event_id":"mirinda-move","due":90,"kind":"MOVE","actor":"MIRINDA","destination":"ROOM"},
  {"event_id":"meet","due":120,"kind":"MEET","actor":"LILI","participant":"MIRINDA","dependencies":["lili-move","mirinda-move"]}
]
```

Return after sufficient elapsed time or run the deterministic demo test. MOVE checks
presence, mobility, allowed locations and runtime door locks. MEET confirms physical
co-presence only, not dialogue or friendship. Cancelled prerequisites cancel dependent
events. Private results stay out of the public recap. This is **not** the complete
Lili/Mirinda acceptance demo with goals, distinct beliefs and social reasoning.

## Verification

Use the normal project test environment and test-only secrets:

```sh
poetry run pytest -q tests/test_living_world.py tests/test_living_world_api.py tests/test_living_world_lifecycle.py
poetry run pytest -q tests/test_turn_replay.py tests/test_staged_world_checkpoints.py tests/test_session_mutation_concurrency.py tests/test_vn_concurrency.py tests/test_narration_regeneration.py tests/test_adventures_api.py
poetry run mypy backend/engine/living_world backend/api/routes/adventures/living_world.py --follow-imports=silent
cd frontend
node --test tests/livingWorld.test.mjs
npm run build
```

Coverage includes 72-hour absence, duplicate requests, concurrent clients, zero/event
budgets, clock regression, causal ordering, unavailable reasoning, impossible meetings,
runtime locks, failure between commits, checkpoint rewind, export and migration
upgrade/downgrade. Frontend tests mock browser lifecycle; no real-browser E2E or real
GPU/Concordia test has been performed.

Recorded verification for this slice: 22 Living World pytest cases and 137 existing
regression cases passed; four frontend lifecycle cases passed; Vite production build,
Ruff checks/formatting of modified Python files and mypy on the eight new backend
modules passed. The entire repository suite was not rerun. Existing dependency
deprecation warnings and the Vite large-chunk warning remain.

## Remaining work

The queue is capped at 512 events without silent pruning. No recurring schedule
compiler, NPC belief store, reflection, LLM/token budget, private-journal UI or
Concordia adapter is shipped. Movement is an adjacent-scene rule and does not execute
player traversal scripts or infer access to scripted areas. Use simple unscripted
test locations.

Before adding autonomous inference, implement a shared reservation for foreground
and maintenance calls, including an unresolved-remote-request state after timeout.
The existing idle scheduler cannot prove remote computation stopped on cancellation.
See the architecture document for the precise integration boundaries and next stages.
