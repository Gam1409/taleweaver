# CI checks and historical failure audit

## Current workflow contract

The [CI workflow](../../.github/workflows/ci.yml) runs independent checks with
fail-fast disabled. Failures retain their exit status; logs piped to `tee` still
fail their job. Python 3.12 and Node.js 22 are the CI environments.

| Area | Checks |
| --- | --- |
| Backend | Ruff lint/format, full backend mypy, the pytest suite and the optional Concordia adapter matrix |
| Frontend | ESLint, TypeScript, every `tests/*.test.mjs` file and the production build |
| Security | Dependency audits and Python/JavaScript CodeQL in the [security workflow](../../.github/workflows/security.yml) |

Backend test jobs generate disposable signing/encryption keys and use isolated
test databases. They do not need deployment credentials. Type, pytest/JUnit and
frontend reports are uploaded by their respective jobs; a green job is evidence
for its exact checked commit, not every server/model combination or a live playthrough.

## Historical audit at `daf66f4c`

The following findings and counts describe that earlier revision. They are kept
as a maintenance record and must not be read as the current repository's type or
test status. Use the latest workflow result for the revision being reviewed.

The complete log for [run 40474146709](https://github.com/Gam1409/taleweaver/actions/runs/40474146709)
at `daf66f4c` shows:

| Check | Actual result |
| --- | --- |
| Ruff lint and formatting | Passed |
| mypy | 2,496 errors in 265 files, status hidden by `|| true` |
| pytest | Failed to import conftest because `SECRET_KEY` was missing; no tests ran, status hidden by `|| true` |

The green workflow status was therefore not evidence of a successful type check
or test run. Local regression results recorded in `ruff-refactor.md` are separate
from this GitHub run.

## Type error categories

The largest groups are `attr-defined` (771), `no-untyped-def` (638), `arg-type`
(332), `union-attr` (273), `assignment` (146), `no-any-return` (81), and
`return-value` (45). Many extracted mixins access state supplied by their manager
without a typed context contract. Other errors involve legacy SQLAlchemy column
annotations and session objects declared optional before they are loaded.
These categories require case-by-case review; they do not establish that every
reported attribute is absent at runtime.

## Confirmed facade defects addressed

`GameTurnManager` forwards calls into interaction, combat and guardrail handlers.
Its existing forwarding methods had drifted from those handlers:

- A switch command returns an awaited string, not an async iterator. Enemy-turn
  output is an async iterator, not a coroutine returning an iterator. These two
  facade implementations were unusable with their intended consumption pattern.
- Container resolution returns three values. Raw container contents may include
  IDs as well as dictionaries; normalization resolves those IDs asynchronously.
- Container movement and clearing return `None` or a boolean, not result tuples
  or item lists. Several combat/guardrail methods likewise had incorrect result
  annotations or hidden coroutine returns.

The corrected facades have explicit parameters and mirror their delegates'
return types and coroutine/async-generator behavior. Ordinary internal handlers
were often called directly, which explains why previous route tests did not
exercise these facade defects. New tests call the facade itself, including real
database-backed container lookup and item movement, and check delegate contracts.

That audit baseline declared Python 3.10 compatibility. Diagnostics imported
`override` from `typing_extensions`, rather than assuming Python 3.12's `typing`.
The current package requires Python `>=3.11,<3.14`; the older lint/type-checking
target in `pyproject.toml` does not lower the runtime dependency requirement.

The local post-fix run at that time reported 2,426 mypy errors across 265 files. None
occur in the 40 corrected facade methods. The focused game/switch/container/
combat suite and direct facade cases pass; diagnostics tests also pass. This
is a bounded contract fix, not a completed repository-wide typing migration.

## CI behavior introduced by that change

Lint, typing and tests run as independent matrix jobs with fail-fast disabled.
Failures retain their exit status. The test job creates fresh authentication and
encryption keys; it does not use deployment credentials or a production `.env`.
Typing output, pytest output and JUnit reports are uploaded even after failures.

The remaining typing debt and then-recorded test failures made their jobs red.
That change restored truthful reporting without claiming to resolve every type
error; later repairs and their verification belong to their own revisions.
