# Agent Guidelines

Detailed architectural guidance and workflows are defined in [Copilot Instructions](.github/copilot-instructions.md).

> [!IMPORTANT]
> **Language Rule**: All texts, UI labels, buttons, tooltips, documentation, comments, and agent communications must be kept strictly in **English** until the user explicitly specifies otherwise.

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
   - Never suppress complexity (`C901`, `PLR0912`, `PLR0915`) or security (`S`) warnings with `# noqa`; refactor the code instead.
   - Full check / fix command: `poetry run python scripts/lint.py --fix`.



