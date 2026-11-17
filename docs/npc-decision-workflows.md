# NPC decision workflows

See [observable state tools](npc-observable-state.md) for current actor/item
inspection within the existing optional agent rounds.

Open **Session settings → NPC Personality**. Enabled mode offers two workflows:

- **Staged** is the existing default. Optional memory investigation runs first,
  followed by the complete source-bound decision request.
- **Integrated** is experimental. Each response can request memory functions or
  submit the complete decision. A model with sufficient information can decide
  immediately, without a separate readiness response. Tool results rebuild the
  same cognitive context before the next request.

The setting also appears in adventure defaults for future sessions. Changing it
in a session preserves that session's minds, notebook, agenda and witnessed memory.
Old saves load as Staged. With zero tool rounds, both use the existing decision
path; Observe mode also keeps its existing path. No schema-version bump is needed.

## Contracts and limits

Integrated reuses the native function adapter or its JSON compatibility port.
The model chooses the existing observer-scoped memory functions or the separate
`submit_decision` function. A decision cannot share a response with memory calls.
Memory batches retain argument validation and at most two operations per round.
After the selected memory-round limit, only submission remains available.

For N configured memory rounds, there are at most N + 1 initial workflow requests,
including failed tool responses. An early decision can use fewer calls. One
completed protocol error may receive bounded host feedback while memory rounds
remain. Its correction consumes an existing round and the normal request reserve;
it does not add another allowance. Feedback identifies malformed structure, extra
top-level fields, missing submission, mixed submission/memory calls or unavailable
functions. No operation from the rejected response executes. Previously successful
operations remain staged and must not be repeated merely to repair the format.

Semantic correction feedback names a recall-only experience's exact array entry.
The model may omit that unsupported optional entry while retaining other valid
entries, or cite a genuine current trigger. Adding unrelated current evidence is
not a correction. A maintained intention also requires `choice.change_basis=[]`;
this independent diagnostic is retained beside structural errors within the same
bounded feedback budget. These hints do not choose the NPC's course, change the
validation guards or grant another repair request.

An invalid final proposal uses the existing single semantic proposal repair and
turn-wide reserve. Source, motive and continuity validators still apply after
every correction. Native plain-text JSON proposals pass through the same final
validator and retain the function-argument size, UTF-8, finite-number and depth
guards. Portable JSON requires its `requests` envelope; an empty array is not a
completed Integrated decision. Failed/unknown provider completion flags, transport
failures and truncated output do not acquire another retry. The role's output
limit still applies; integrated responses use the decision-token budget because
they may contain a complete proposal.

JSON compatibility uses the configured provider's structured-output policy when
its text port supports that option. Schema-capable modes receive an outer envelope
for the currently offered functions: submission alone, or up to two nonfinal calls.
Memory-only investigation still permits an empty ready reply. Arguments remain
ordinary JSON objects validated by their existing owners. Provider fallbacks and
prompt-only ports remain available; requesting a format does not establish remote
enforcement. The selected format counts against the existing input budget, and a
rejection or timeout never triggers a retry without it. Local envelope, argument,
source and world checks still run even if the server ignores its output format.

Corrected protocol errors appear as `invalid_envelope` audit entries with bounded
technical codes. Failed requests count against call and round limits. A second
protocol error or an error on the final available round ends preparation; failed
or cancelled turns do not publish staged notebook writes. These checks establish
protocol and transaction behavior, not live-model reliability.

A complete native text proposal without a function wrapper can use the same
proposal validator directly. It retains the function-argument size, strict JSON,
UTF-8 and depth limits and increments the local-format-correction counter. This
does not establish semantic validity; the ordinary proposal checks still apply.

Selecting Integrated in the session or adventure-default controls raises the draft
input budget to at least 48,000 characters and preserves larger values. The value
remains editable before saving; switching back to Staged retains it for comparison.
After a successful session-settings commit, increases produce a server `WARNING`
containing the old limit, new limit and workflow. Failed, stale, unchanged and
decreasing updates produce no increase warning. Logs contain no scene or notebook
content or actor/session identifiers.

Runtime never increases the saved limit. Combining decision instructions,
source bindings and tool definitions can exceed an input budget that fits the
separate staged requests. Such input is rejected before model dispatch, preserving
the prior state. Configure any larger budget explicitly and use the same budget
for a controlled comparison. No canonical history or source evidence is discarded
to conceal an input failure.

Both workflows use the same complete appraisal, experience, development, agenda,
motive and intention validators. A private note is not witnessed evidence. Tools
cannot execute code, access files or networks, read another notebook or mutate
world items. Notebook writes remain detached until the reviewed turn commits;
failure and cancellation prevent their publication. Ordinary world-action,
ownership, item-identity and player-agency checks remain in their existing owners.

## Compare an equivalent turn

1. Keep the model, source state, active NPCs, tool rounds and limits unchanged.
2. Save Staged, run the turn and inspect **Last NPC analysis timings**.
3. Save Integrated and regenerate from the same pre-turn state, then inspect it
   again. Notebook contents retain their latest state during regeneration; if
   either run edits notes, the second run is no longer a strictly matched trial.
4. Compare preparation wall time, calls, request phases and available provider
   timings. Request durations can overlap; do not add them as turn wall time.

The saved usage records the workflow actually used. Selecting another workflow
does not relabel older timings; legacy results explicitly show an unknown mode.
Offline tests establish contracts and transaction behavior, not a speed gain or
live-model interpretation quality. Repeated matched live runs are needed to
measure either.

Session settings give **Living World** and **NPC Personality** their own navigation
sections. **Characters** retains portrait presentation. Switching sections keeps
forms mounted and preserves unsaved drafts; save failures reveal their own section.
