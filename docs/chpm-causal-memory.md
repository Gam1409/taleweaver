# NPC Personality 1.1.0: causal continuity

An NPC can remember "go to the laboratory" while losing why the trip mattered or
where the already collected sample is kept. Repeating a goal or retrieving a few
recent lines does not preserve this causal chain. The live reviewer now may record
compact, observer-specific threads: **purpose → cause → event → consequence →
next step**. Every changed field cites an exact passage of the accepted assistant
reply. The original messages remain the evidence.

The short thread is a current view over an immutable evidence graph. Each changed
statement has its own source-bound node; optional directed links describe what
motivated, caused, enabled, changed or resolved another statement. Links retain
their passage and distinguish explicit narration from a model inference. Message
order alone never creates a causal link. Changes append a new thread transition,
preserving previous statements and links without replaying them in the prompt.

For example, a thread can retain "analyse the collected sample", "sample already
collected", and "sample in the doctor's inner coat pocket". A later arrival updates
the event; omitted cause and consequence fields remain intact. An explicit handover
or analysis updates those fields or closes the thread. Unrelated dialogue, a new
location and elapsed message counts do not close it.

## Execution and cost

The existing live narration review produces optional `causal_updates`; there is no
additional model request. Cognition, narration, review and ordinary fallback all
receive the small current thread view. Original causal excerpts are pinned into
cognition even when lexical RAG misses, the player's reply is short, the transcript
window is zero, or agent lookups are disabled. Pinned excerpts share the existing
eight-source / 6,000-character tool handoff budget, so configured agent lookups
cannot expand that budget independently.

Each NPC retains up to three open threads, each with up to five short fields of
180 characters. Normal turns with one thread add a few hundred input tokens per
relevant request; full limits cost more and still obey the configured input cap.
Quotes and hashes stay in the save instead of being repeated in the current view.
The reviewer writes only changed fields. Exact token cost depends on language,
number of participants and the model tokenizer; no fixed token estimate is a cap.

## Evidence, privacy and boundaries

Only controlled NPCs can receive updates, at most one per NPC per accepted turn.
The reviewer must exclude unperceived events, other people's private thoughts and
hidden conditions. Attribution and causal interpretation remain model judgments;
literal quotation alone cannot prove them. New facts must cite this reply, not a
player request, hypothetical action or invented past event. A future `next_step`
does not become a completed `event`. The host checks IDs, passages, session, role,
revision and whole-message hash. It never modifies inventory, clothing, location,
physiology, traits or relationships from these notes. Narration excerpts enter the
observer ledger as **reported narration**, not authoritative host observations.
New explicit host outcomes take precedence.

Malformed optional updates are skipped with an administrator audit note; they do
not reject otherwise valid narration or replace the previous thread. Rejected or
simplified/unreviewed replies cannot create confirmed causal notes. Fallback keeps
previous verified threads as historical context and explicitly acknowledges the
unreviewed continuity gap.

Source edits/deletions invalidate dependent threads. Regeneration and replay retain
the historical state; settings changes never copy completed-turn facts into their
own pre-turn snapshot. Session forks rebind complete source chains; foreign or
incomplete chains cannot be recalled. Original personality remains untouched.
Rewinding a later transition restores the earlier retained thread view, including
an earlier unresolved state. Link endpoints are restricted to earlier statements
of the same observer and thread; foreign or broken dependencies reject a save.

## Finite storage and existing sessions

Three recent closed threads per NPC remain saved; the prompt shows only the latest
closed thread alongside open ones. Older closed threads leave this recent view
with an audit note; their original messages and established core evidence remain
in history. At the open-thread cap, a further opening is skipped visibly in the
audit while all existing open threads are preserved. There is no turn failure or
silent eviction of an open goal. A causal update records at most five new evidence
passages, five statement nodes, three influence links and one transition, included
in pre-turn capacity reservation. The full graph stays in the administrator's
psychology source ledger; requests receive only the current fields and up to three
relevant links. Inferred links are fallible, not independent proof of world facts.

This is additive state with empty defaults: saved kernel schema version remains 6.
Old sessions load without inventing causal records. The module begins extracting
from newly accepted replies; it does **not** retrospectively reconstruct an old
conversation. Existing declared goals still retain their separate source-checked
ledger, now passed in full to the narrator/reviewer rather than only as selected
motives. Model quality and old-history reconstruction require separate live checks.

## Beyond this release

These are observer-owned causal accounts, not a complete physical or political
simulation. Body/skin conditions need a separate host state lifecycle: origin,
affected region, visibility and explicit resolution, rather than an emotion or an
inventory flag. A narrated circumstance can be retained here without becoming a
server-verified physiological condition.

An intrigue spanning a cardinal, messenger, secretary and king also needs distinct
world events, observations, transmitted reports and personal interpretations.
Seeing a vase removed is not the same as learning who removed it or why; receiving
a report does not establish its truth. This graph forbids cross-observer links and
does not automatically give other NPCs knowledge, run inactive characters' private
decisions or force downstream outcomes. A future shared event layer must retain
that separation and supply each NPC only its accessible portion of the chain.

Further agent retrieval should build an observer-specific situation view: pinned
identity and abilities; own current possessions and conditions; visible environment
and participant changes; known relationships and their sources; ongoing purposes,
desires and relevant past actions. Authored ability is distinct from an available
tool, and a reported claim or subjective relationship estimate is distinct from a
host fact. Hidden conditions and other NPCs' private desires are not public data.

Filter by session, canonical actor IDs and observer access **before** ranking
memory. Then retrieve a bounded episode and its relevant cause/consequence links,
not only the closest text fragment. A read-only agent can request a specific
missing detail and stop when it has enough evidence. Shared limits must include
all retrieved quotes and graph expansion; twenty present NPCs must not imply
twenty complete dossiers or an unbounded chain of model calls on every turn.
