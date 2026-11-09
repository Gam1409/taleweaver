# TaleWeaver Agent Guidelines

Welcome to the TaleWeaver workspace! This project uses the **Antigravity Customization System** with progressive disclosure rules, on-demand skills, and guidelines aligned with [Copilot Instructions](.github/copilot-instructions.md).

> [!IMPORTANT]
> **Language Rule**: All texts, UI labels, buttons, tooltips, documentation, comments, and agent communications must be kept strictly in **English** until the user explicitly specifies otherwise.

---

## Core Engineering Rules

1. **Clean Code & Modularity (No Monster Files)**:
   - Target module size is **< 400 lines** (max warning threshold: 600 lines).
   - **Never dump new features or monolithic code directly into existing oversized files** (`editor.py`, `gameplay_logic.py`, `templates.py`, `turn_guardrails.py`, `llm_router.py`, etc.).
   - Extract domain logic, database operations, or state handlers into separate service modules, subpackages, or helper classes.

2. **Control Flow Complexity & Flat Nesting**:
   - **Maximum nesting depth of 2.** Invert `if` checks and use **Guard Clauses / Early Returns** (`if not condition: return/raise`) to keep execution linear.
   - Combine simple conditions (`SIM102`) and replace long `if/elif` ladders with dispatch dictionaries, strategy handlers, or `match / case`.
   - Never write single-line compound statements (`if x: return y` - `E701`).

3. **Mandatory Linter & Security Protocol**:
   - Before completing ANY task, agents **must** run:
     ```bash
     poetry run ruff check <modified_files>
     poetry run ruff format --check <modified_files>
     ```
   - Ensure **zero errors** before concluding.
   - Before every push containing frontend changes, run the complete frontend suite from `frontend/`: `node --test tests/*.test.mjs`. Targeted scripts such as `test:presets` supplement this check; they do not replace it. Resolve failures before publishing.
   - Never suppress complexity (`C901`, `PLR0912`, `PLR0915`) or security (`S`) warnings with `# noqa`; refactor the code instead.
   - Full check / fix command: `poetry run python scripts/lint.py --fix`.

4. **Regression Prevention (Owner Requirement)**:
   - Preserve working behavior when extending the project. For each reproducible bug,
     add a regression test that fails before the fix, then verify the affected feature
     and its integration boundaries before publishing.
   - Check combinations of features and exact limits, not only each feature in isolation.
     Producer, consumer, and persistence limits must agree. Every successfully saved
     state must load again; reject invalid updates before replacing the previous state.
   - Do not hide regressions by dropping assertions, silently discarding canonical
     history, or increasing limits without addressing the cause. Add no extra paid
     model requests merely to mask a host bug.
   - Distinguish verified fixes from known remaining issues. Passing mock/schema tests
     does not establish psychological quality or live-model reliability.

5. **Release History and Schema Discipline (Owner Requirement)**:
   - Bump persisted schema versions only for incompatible data-shape changes, not
     additive fields with safe defaults. Verify legacy loading explicitly.
   - Collect prompt-only edits into one final `prompt tuning` commit per work wave.
   - Keep each behavior change in a coherent commit. The CHPM pilot has already
     been integrated; do not rewrite published history to follow obsolete hashes.

6. **Existing Functionality Before Design (Owner Requirement)**:
   - Before choosing a design or implementing a behavior change, complete a search
     of the relevant existing code, documentation, tests and runtime call sites.
     Include optional/disabled features, fallback paths and recently added code,
     including code written by the current agent.
   - Trace where the required facts are produced, stored, updated, validated and
     consumed. Check configuration gates and lifecycle paths such as failure,
     retry, regeneration, copy/import and replay. Distinguish missing functionality
     from an existing capability whose integration is incomplete or broken.
   - Make the implementation decision only after that investigation: reuse an
     existing capability, repair its integration, extend its current owner, or add
     a component for a demonstrated gap. State the evidence and why an extension
     would or would not cover the requirement.
   - Preserve existing sources of truth, identifiers, schemas, provenance,
     visibility rules, game clocks and transaction boundaries. Do not introduce
     parallel state stores, extraction requests or prompt layers for behavior
     already owned by another mechanism without demonstrating the need.
   - Prefer the smallest coherent change that satisfies the requirement. A new
     framework, service or registry is not the default solution.

---

## 1. Portable project references

The checked-in [Copilot Instructions](.github/copilot-instructions.md) contain
Python, TypeScript, testing, security and migration rules. They are authoritative
on every machine; an ignored `.agents/` directory is optional local tooling.

- [Turn pipeline](docs/diagrams/game_session_loop.mermaid)
- [Adventure format](docs/specs/adventure_format.md)
- [Living World architecture](docs/living-world-architecture.md)
- [NPC Personality pilot](docs/chpm-pilot.md)
- [Database inspector](scripts/inspect_state.py): list-adventures, show-adventure,
  list-sessions and show-session; use it before changing state logic.

## 2. Local tools

Optional private skills must not be required to build, test or review this
repository. Use the checked-in scripts and documentation when they are absent.

---

## 3. Agent-Friendly Command Execution

To prevent terminal commands from hanging or consuming excessive tokens:

* **Avoid Terminal Pagers:** Always run Git commands with `--no-pager` (e.g. `git --no-pager diff`, `git --no-pager log -n 5`).
* **Prevent Token Flooding:** Never dump huge files directly to terminal output; use `head -n 50 <file>` or targeted views.
