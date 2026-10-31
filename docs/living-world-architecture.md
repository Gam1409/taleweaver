# Living World architecture audit

Experimental branch: `experiment/living-world-concordia`, based on `6ad19d20`.
The feature is opt-in per session. Main and the Mature prompt hooks are unchanged.

## Existing integration points

| Concern | Existing implementation | Integration decision |
| --- | --- | --- |
| Canonical world | `SessionState`, session-owned `WorldEntity`, `WorldScene`, `WorldExit` | Reuse canonical positions and game minutes. |
| Session serialization | `visual_novel/concurrency.py`, `session_mutations.py` | Share the nonblocking session write lease. The supported launcher is single-worker. |
| Foreground priority | `memory_rag/scheduling.py` | Do not introduce another background LLM loop. |
| Regenerate | `turn_replay/snapshot.py` snapshots SQL columns | Store simulation persistence on SessionState so snapshots remain atomic. |
| Chronicles | `session_checkpoint_service.py` explicitly selects fields | Add simulation snapshot and restore hook; fork timeline identity on rewind. |
| Export/import/copy | `session_exporter.py`, `import_restore_session_bundle.py`, `session_copy_state.py` | Export state, validate imports, reset presence and fork timeline on copy/import. |
| RAG | SQL history and summaries with LanceDB derived indexes | No parallel RAG; private simulation plans must not enter recall as facts. |
| NPC relationships | `visual_novel/social.py`, NPC journal | Existing player relationships are not a complete NPC-to-NPC simulation. |
| UI | `SessionSettingsModal.vue`, `useSessionPlaytime.ts`, `GameView.vue` | Add opt-in session controls and independent presence lifecycle. |
| Localization | English UI strings; no vue-i18n dependency/catalog found | Match the existing English UI, keep new strings together. |

## Persistence boundary

Use a nullable JSON column `SessionState.living_world` for the first vertical slice.
This is SQL persistence, not an in-memory queue or a second vector database. It keeps
the timeline, settings, clocks and bounded queue in the same transaction and existing
snapshot as canonical changes. A separate indexed event table is appropriate before
unbounded world histories; do not silently discard committed events to fit a limit.

There are four distinct clocks: server UTC presence, canonical `in_game_time`, the
committed simulation cursor, and the requested catch-up target. Only committed steps
may advance the cursor. PAUSE never converts offline UTC into game minutes. Presence
heartbeats do not execute events or invoke LLMs. CATCH_UP must retain its unprocessed
target, and a waiting decision must stop dependent advancement.

## Work stages and limits

1. Persistence, PAUSE, presence, owner-scoped controls, snapshot lifecycle and tests.
2. Bounded rules-only catch-up, deterministic event execution and recovery tests.
3. Private NPC deliberation after inference serialization and late-response fencing.
4. Optional Concordia adapter, followed by actual adapter compatibility tests.

The existing idle scheduler does not ensure remote generation stops on timeout. A
local cancellation alone must not be treated as proof that the GPU is free. Do not
enable autonomous remote reasoning until its lifecycle is correctly fenced against
foreground generation. Process-local session leases do not support multi-worker
deployment; enabling the experiment does not change that deployment contract.

## Concordia reconnaissance

PyPI `gdm-concordia==2.4.0` declares Python >=3.12 and Apache 2.0. TaleWeaver supports
Python >=3.10,<3.14. Its dependencies include numpy>=1.26, pandas, matplotlib, IPython,
reactivex and tenacity; provider integrations are extras. A required dependency would
break supported Python versions. Use an optional, version-pinned adapter on Python
3.12/3.13, with no automatic package installation on normal game startup.

Sources: https://pypi.org/pypi/gdm-concordia/json and
https://github.com/google-deepmind/concordia . Metadata verification is not an
integration test; no claim of a working Concordia adapter is made at this stage.
