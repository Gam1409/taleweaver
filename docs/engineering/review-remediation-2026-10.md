# Review remediation: experimental Living World branch

This change addresses the runtime defects reproduced in the October review. It
stays on `experiment/living-world-concordia`; it does not enable autonomous NPC
reasoning or merge the experiment into the main branch.

| Finding | Result |
| --- | --- |
| R01: SQLite writer held across model waits | Recoverable ordinary turns and replays release their write transactions at model boundaries, including recall preparation. Normal turns keep a durable recovery snapshot that retains the submitted input. Failure, stream cancellation and restart recover it. Repeating the failed input reuses its message. |
| R02: executable imported assets | ADZ/ADS accept media assets only. Public data serving uses a media extension allowlist, `nosniff`, and a restrictive sandbox CSP, including for legacy SVG placeholders. HTML/JS and other runtime files are denied. |
| R03: foreign private template link | ADS keeps a template link only for the owner or a ready/public adventure. Other imports use their saved snapshot without accessing the private template. |
| R04: lost simulation on ADS import | ADS restores and validates Living World state, forks its timeline, and resets the absence baseline. |
| R05: unbounded ADS archive | Upload bytes, entry count, individual/total unpacked size, compression ratio, paths and duplicate members are checked. Extraction copies bounded chunks; failed ADS imports remove their new asset directory. |
| R06: public inference journal | JSON and temporary files are denied by the public media policy. The journal remains at its existing location so unresolved inference reservations are not discarded. |
| R07: current-time dependency barrier | Due pending events block CATCH_UP foreground turns even when target equals cursor. PAUSE and disabled mode retain their semantics. |
| R08: stale portrait after rewind | A session-owned request token is compared atomically before applying a portrait. Rewinds/checkpoint restores invalidate pending tokens. Unrelated current state is preserved. Manual and automatic portraits share this path. |
| R09: stale container location | Container access uses session overrides for location, visibility and inventory membership, with case-insensitive names/IDs. |
| R10: incomplete narration learned as fact | Partial narration remains visible but has a durable `incomplete` journal status. Journal scheduling, canonical RAG sources and chronicle compression exclude it. Successful rewriting uses the existing evidence refresh path. Legacy messages keep their previous interpretation. |
| R11: full foreground memory materialization | Foreground recall loads a bounded source set, verifies canonical hashes and keeps epoch/scope fences. Recent/lexical sources, selected NPC evidence and summary dependencies share a 320-message budget. Idle indexing retains full-corpus behavior. |
| R12: CI gaps and stale tests | Migration tests discover the single Alembic head. Frontend tests match current component contracts. CI runs on experimental branches and by manual dispatch, with independent frontend test/build/type jobs and reports. |
| R13: engine/API import cycle | Portrait settings read the existing snapshot directly, removing the eager engine-to-route dependency. SessionImporter is tested in a fresh Python process. |

## Boundaries still requiring separate work

- Short transactions rely on the existing single-worker session mutation lease
  and durable turn snapshots. Legacy shared avatars, slash-only commands and the
  adventure generator do not gain rollback guarantees from this change; their
  previous transaction policy is retained. Multi-worker deployment still needs
  a shared lease/version protocol.
- Recall limits bound foreground materialization, not every database scan. SQL
  lexical fallback can scan older text, and idle indexing still reconstructs its
  canonical corpus. A persisted incremental source table/lexical index is a
  separate storage migration, not silently introduced here.
- Type-checking debt remains visible. The backend baseline was 2,145 errors;
  this change reduces it to 2,134. Frontend type checking also exposes 142 existing
  errors. Neither check is suppressed or marked successful when it fails.
- The media policy is not per-session authentication: supported media URLs remain
  public as before. Archive media are rendered under a sandbox; arbitrary runtime
  data cannot be downloaded through `/data`.

## Verification

Regression coverage lives in `tests/test_review_regressions.py` and
`tests/test_review_state_regressions.py`. It exercises file-backed SQLite writer
contention and recovery, retry/cancellation, archive ownership and round trips,
static security headers, a fresh-process import, timeline fences, effective
container access, incomplete evidence and bounded recall with stale vector IDs.
All model/provider calls in these checks are local fakes; no paid model request is
needed. Existing gameplay, regeneration, portrait and memory suites are retained.

Validation results: the full backend run passed **2,509 tests**. The final Unicode
container/snapshot changes passed a separate 32-test state/portrait/race run;
the final bounded-evidence selection passed 40 memory/state tests. Frontend
passed all 23 test files and its production build. Ruff check and format check
passed for backend, scripts and all modified Python tests. Type checks remain
failing at the documented baselines (2,134 backend / 142 frontend errors).
