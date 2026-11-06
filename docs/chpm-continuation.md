# Keep playing when NPC analysis fails

**NPC Personality 1.0.0** (technical module name: CHPM) adds an optional character and memory layer to Visual Novel
sessions. It helps NPCs respond from their own traits, values, goals and witnessed
history. The narrator still writes the story. CHPM remains **off by default**.

For example, a proud mechanic asked to abandon an important repair may negotiate,
refuse, or suggest another time. Repeated kindness may influence later reactions,
but one friendly exchange should not replace the character's original values.
This is the intended behavior, not a guarantee that a model always gets it right.

## Choose how to play

Open **Session Memory & Settings → NPC Personality**, choose characters, and
save between turns. Start with one active NPC before increasing the cast.

For an adventure, open **Living World** in the editor's left menu. It contains
Concordia settings and NPC Personality defaults for **new sessions only**. Existing
sessions retain their own settings and psychological history. Session settings use
three columns on wide screens, stacking on smaller screens. **Debug → VN Settings**
provides mature-content controls and technical Concordia/Personality diagnostics.

| Mode | What changes |
| --- | --- |
| Standard | Existing narration, without CHPM requests. |
| Observe | Calculate decisions for inspection; ordinary narration continues. |
| Enabled | Give the narrator character intentions and review its reply before display. |

Enabled mode offers two failure policies:

- **Keep playing** is the default for enabled CHPM. If optional analysis fails,
  continue with standard RP using the last confirmed character identity and
  current scene facts. An amber **NPC Personality: simplified RP** indicator appears
  outside the story text, and survives reloading the session.
- **Strict** stops a failed turn for inspection and preserves the previous
  rollback behavior. Use it when evaluating models or investigating a problem.

Living World private decisions must be disabled before enabling CHPM. The two
systems should not independently decide for the same characters.

## What happens on a failure

| Failure | Keep playing behavior |
| --- | --- |
| Invalid analysis JSON, unusable proposals, or an analysis capacity limit | Abandon proposed psychological updates; use standard narration. |
| A review is unavailable or malformed, with no known rejection of the current text | Keep that reply as explicitly unreviewed RP; do not dispatch another narrator request. |
| The reviewer rejects text | Try the existing single repair and review when the request budget allows. If still rejected or repair fails, request at most one fresh standard reply. Never release the known rejected text. |
| A nonempty narrator stream ends early | Preserve the host's ordinary partial-response behavior and warning; no psychological update is confirmed. |
| Two analysis/review failures | Use standard RP for the next three completed turns, then attempt CHPM again. |
| Session scope mismatch, invalid saved psychology, conflicting save, or failed database commit | Stop safely. These are integrity failures, not optional analysis failures. |

The additional standard reply uses the configured **Complex** narrator role,
with at most 4,096 output tokens. It is separate from the CHPM logical request
budget. It is used only after a known rejection; it is not a transport retry.
Normal router admission and uncertain-request protection still apply. A server
that cannot produce any usable response cannot be made available by this policy.

## What is remembered

Simplified RP is saved in the ordinary conversation history. The last confirmed
psychological state, declared agenda and observer memory stay unchanged. A failed
proposal never becomes a confirmed personality change or promise.

CHPM records a continuity gap. On return, it refreshes current host observations,
avoids reusing an intention from before the gap, and labels pre-gap emotional
estimates as historical with current intensity unknown. It does **not** silently
reconstruct confirmed psychological memory from the unreviewed dialogue. Events
from that interval can therefore be missing from CHPM's observer memory even
though they remain in the story. A new successful review closes the pending gap;
it does not claim to have verified the missing interval.

The most recent eight simplified replies retain diagnostic source IDs and hashes.
This bounded window is not a transcript or memory archive. Cumulative counts are
kept separately, and canonical chat messages are not deleted when it rotates.
Session copies rebind diagnostic message IDs; checkpoints and full turn replay
restore the saved recovery state. Source edits remove matching diagnostic
references and invalidate dependent psychology through the existing source checks.

## Cost and limits

Standard mode adds no CHPM requests. Enabled mode normally uses one perception
request, one decision proposal per active NPC, and one shared review, in addition
to the normal narrator. Agent lookup rounds and needed repairs add requests.
The settings panel shows the required request reserve for the selected cast.
Unused reserve is not spent. Provider-level attempts may add cost.

Enabled replies are buffered until review and the recoverable save boundary.
The interface shows progress while waiting; generated prose does not stream in
this mode. Several active NPCs on a slow local model can take minutes. A roster
of 20 does not require 20 deeply processed NPCs every turn: the default active
limit is three. Increasing that limit increases cost and waiting.

The module is experimental. Exact quotation and scope checks protect provenance;
they do not establish psychological accuracy. Recall is bounded and partly
lexical, storage is finite, and LLM reviewers can miss mistakes. Recovery behavior
is covered by local mocked integration tests; it has not received another live
model benchmark in this release wave.

For implementation details see [the pilot guide](chpm-pilot.md),
[agent reads](chpm-agent.md), and [evaluation](chpm-evaluation.md).
