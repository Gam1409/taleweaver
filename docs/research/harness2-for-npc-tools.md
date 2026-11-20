# Harness² and NPC action tools

Research date: 2026-11-17. Reviewed upstream revision:
[`6868817518876de8fd170c6a8354daca273b6191`](https://github.com/google-research/harness2/tree/6868817518876de8fd170c6a8354daca273b6191).
This is a design assessment, not an installed integration or a measured improvement
in TaleWeaver. The upstream repository licenses its own code under Apache 2.0;
its bundled third-party components retain separate licenses. No upstream code is
copied into the engine by this assessment.

## What the project actually does

Harness² keeps model weights fixed and optimizes the surrounding harness through
**Propose–Probe–Compose**. It runs reference executions, proposes general and
domain-specific edits, executes candidate harnesses on the same task, and composes
an adopted harness using the contrasting evidence. A separate reflection step
retains a supported lesson for later tasks in the same domain.

Its editable surfaces include prompts, guidance, memory, skills, subagents,
scripts and plugins. Execution uses Codex or OpenCode, rather than providing a
drop-in OpenAI function-call decoder or a game-state transaction manager.
The professional-work benchmark results in its README do not establish reliable
NPC autonomy, emotional fidelity or local small-model performance.

Sources: [README](https://github.com/google-research/harness2/blob/6868817518876de8fd170c6a8354daca273b6191/README.md),
[benchmark adapter contract](https://github.com/google-research/harness2/blob/6868817518876de8fd170c6a8354daca273b6191/harness2/core/spec.py),
[recursion implementation](https://github.com/google-research/harness2/blob/6868817518876de8fd170c6a8354daca273b6191/harness2/core/recursion.py).

## Useful transfers into our existing test harness

| Upstream mechanism | Application to NPC testing | Boundary |
| --- | --- | --- |
| Compare reference and candidate trajectories on the same input | Freeze the world fixture, source history, model configuration, limits and transport; change one tool/prompt design at a time | Never run a probe against a player's live mutable session |
| Separate method, execution adapter and benchmark | Keep scenario/oracle definitions independent of native versus JSON ports and model configuration | Reuse existing router, owners and turn coordinator |
| Record `[ACTION]`, `[OBSERVATION]`, `[ERROR]` trajectories | Correlate offered schema, actual call, tool outcome, final saved state and next-turn observation | Do not treat a plan, tool attempt or fluent narration as completion |
| Actionable rejection feedback with a bounded correction | Explain the invalid field or prerequisite and preserve earlier successful work | Retain our finite request budget and uncertain-transport policy |
| Per-domain lessons with cue, evidence and confidence | Retain a concise engineering explanation for a reproducible protocol failure | This is developer test memory, not an NPC's private notebook or world lore |
| Stable candidate anonymization | Blind an optional prose/emotion assessor to baseline/candidate labels | Deterministic state assertions remain the primary correctness oracle |
| Isolated rollouts and reproducible resume | Fresh session/database/notebook for each alternative; resume only identical configuration | No cross-run state contamination; record failures and timeouts explicitly |
| Evidence-preserving context construction | Keep the state evidence needed to assess an action, and mark omissions | A clipped transcript cannot establish that an action never happened |

Sources: [context](https://github.com/google-research/harness2/blob/6868817518876de8fd170c6a8354daca273b6191/harness2/core/context.py),
[proposer](https://github.com/google-research/harness2/blob/6868817518876de8fd170c6a8354daca273b6191/harness2/core/proposer.py),
[selection and reflection](https://github.com/google-research/harness2/blob/6868817518876de8fd170c6a8354daca273b6191/harness2/core/selection.py),
[library](https://github.com/google-research/harness2/blob/6868817518876de8fd170c6a8354daca273b6191/harness2/core/library.py),
[rollout isolation tests](https://github.com/google-research/harness2/blob/6868817518876de8fd170c6a8354daca273b6191/tests/test_jobbench_rollout_isolation.py).

## Important differences and limits

The released recursion schedule uses `4 × k` executions, including reference runs,
and `3 × k` improvement stages, before additional selection/reflection/evaluation
work. At `k=1`, these are four executions and three improvement stages, not one
ordinary NPC model request. Each execution can itself contain many model calls.
Automatic per-turn adoption would therefore work against the current latency goal.

The released `selection_pool` deliberately contains final compositions only; it
excludes the reference runs. An invalid edit stage can inherit its previous
harness, but this is not a general guarantee that the selected result outperforms
the original. Our comparison must retain the original as an acceptable outcome
and require no regression on held-out scenarios before adopting changes.

Upstream selection has no ground-truth grading feedback while it chooses the
harness. TaleWeaver has stronger available evidence for inventory, ownership,
clothing coverage, poses, resources and location: the authoritative owners and
saved state. Use those exact checks rather than an LLM vote. Human or blinded
model assessment can supplement subjective emotional expression; it cannot
override an ownership failure or prove a character's private intentions.

Upstream executors support scripts and plugins, and its README explicitly notes
unrestricted executor networking and disabled Codex sandboxing. These are
properties of its research environment, not permissions to grant to NPCs.
Our NPC API remains closed, session/observer-bound and data-only. Rules, budgets,
identity, visibility, source checks and state validators are not editable tools.

Sources: [budget ledger](https://github.com/google-research/harness2/blob/6868817518876de8fd170c6a8354daca273b6191/harness2/core/ledger.py),
[experiment guide](https://github.com/google-research/harness2/blob/6868817518876de8fd170c6a8354daca273b6191/docs/EXPERIMENTS.md),
[editable tree validation](https://github.com/google-research/harness2/blob/6868817518876de8fd170c6a8354daca273b6191/harness2/core/tree.py).

## Proposed use in this work

1. Finish owner-backed commands and their state/lifecycle invariants first.
2. Re-audit native and JSON tool transport, availability, errors and call/result
   identity before large live testing.
3. Compare frozen baseline/candidate fixtures with the same budgets and context
   variants. Record offered, attempted, staged, applied, blocked and unexercised
   separately. Preserve the original failed run.
4. Assert the complete path: observed state → choice → tool result → world commit
   → narration inputs → reload → next observation. Keep internal affect separate
   from outward expression, and preserve player agency.
5. Trial optional prompt/tool-description refinements outside gameplay. Keep a
   held-out scenario set and retain the baseline when the evidence is inconclusive.

Self-editing harnesses, automatic production adoption, extra model reflectors on
every turn and execution of generated scripts are not part of the current change.
