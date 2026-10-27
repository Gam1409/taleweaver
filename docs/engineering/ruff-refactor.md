# Backend refactoring and CI lint cleanup

The full CI command (`ruff check backend scripts`) reported 363 findings on
`4bc659ce`. The final `inspect_state.py` warning was one finding, not the cause
of the other failures. CI stopped at lint before running tests.

## Boundaries preserved

- Turn application now calls separate inventory, hook, scene, entity,
  progression, award, and world/time steps. Their order and final flush remain
  unchanged; no intermediate commits were added.
- Interaction commands have dedicated traversal, debug, switch, container and
  slash-command handlers. Existing command entry points, streamed yields and
  pickup narration handoff remain available.
- Session startup, saved-session copying, initial state, sheet hydration and
  asset repair have separate helpers. Inventory visibility, NPC state, authored
  fields, image precedence and ownership checks remain in their original paths.
- Archive, blueprint and session-bundle imports keep their distinct field
  mappings and defaults. Archive safety limits and transaction boundaries are
  retained. Export remains read-only.
- Image providers have separate implementations behind the existing
  `MediaEngine` methods. Provider selection, fallback/retry ordering and image
  persistence behavior are retained.
- SQLAlchemy model registration, public imports and Pydantic schema contracts
  are retained. Legacy exception aliases also keep their diagnostic names.

These extractions are domain-specific steps, not a replacement rules framework.
The change does not add game features, change narrative prompts, migrate saved
games or alter database schemas. Additional untouched files received formatter
changes because CI checks the entire backend and scripts directories.

## Validation approach

Regression suites exercise commands, game turns, wardrobe and ownership,
session startup/copying, import/export, generation, provider failures and upload
security. New contract tests cover mutation ordering, first-item matching,
rollback on a late failure, provider routing, distinct import defaults and
read-only export precedence.

Independent comparisons against the original code verified model/schema
metadata, constructor field mappings, provider error messages and API-key
selection, plus generated placeholder image pixels and SVG output. Full-suite
results are compared with an unchanged checkout so existing failures are not
mistaken for refactoring regressions.

### Recorded validation

- Unchanged `4bc659ce`: 2,083 passed, 23 failed in the full run.
- Refactored snapshot: 2,109 passed, 23 failed; all original tests were retained
  and 26 additional cases were collected at the start of that run.
- The final focused run covered all 39 newly added contract cases plus eight
  diagnostics cases: 47 passed. Thirteen contract cases were added after full
  collection and are included in this focused result instead.
- Migration subprocess and transport timeout checks passed in isolated runs on
  both revisions (five tests each). The initial migration failure was caused by
  a missing multiprocessing entry-point guard in the temporary test runner;
  the transport timing assertion was load-sensitive.
- The only additional failing test in the refactored full run was a randomized
  combat test. Forcing the same special event reproduced its failure on the
  original revision: its LLM factory mock lacked `for_role`. The test now uses
  the real factory contract and explicitly exercises both special-event paths.
  The corrected combat suite passed all 14 cases on both revisions.

The remaining 21 failures also occur before this refactor: 16 adventure API
fixtures use an outdated format; two memory tests lack the manager's user; one
voice-stream test assumes a single chunk; one hard-rule test awaits a synchronous
mock; and one generation test omits the role's token budget. They remain separate
test debt. Production behavior and assertions were not weakened to hide them.

## Deliberate network binding

The user explicitly requested retaining access from other computers. The
existing `0.0.0.0` bind is therefore unchanged, with one local `S104` annotation
documenting that decision. Ruff configuration and complexity thresholds are
unchanged; no general security or complexity rule was disabled.

## CI limitation

The existing workflow suppresses pytest failures with `|| true`. A green workflow
alone therefore proves neither that all tests passed nor that live models were
tested. This refactor does not introduce or expand that exception; local test
results and baseline comparison must be read separately.
