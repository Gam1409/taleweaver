# NPC action autonomy

An NPC owns their intentions and voluntary actions. The player owns their character's
speech, choices, inner state and voluntary responses. An NPC may initiate interaction
with the player; this does not supply the player's acceptance or reply. Existing world
rules determine external consequences, access and capabilities.

## Existing paths

Normal VN narration already supports initiative without NPC Personality. Its current
state, scene and character context guide feasible actions. Completed movement,
possessions, clothing, physical conditions and staging use the existing shared state
check. A player's command or confirmation is not required for an NPC's own action.

Physical placement and ownership are distinct: putting an owned coat on a bench can
retain its canonical owner while recording the coat's scene placement. Removing
clothing does not create a second item or transfer it to the player. Routes, locked
exits, unavailable actors, canonical IDs and explicit failed outcomes remain binding.

NPC Personality adds source-grounded motives and chooses the next intention. The
existing `message_plan` wire field can express speech, a feasible physical action or
both. Its name remains compatible with existing producers and saved intentions.
The narrator can realize the chosen course through compatible practical steps; it
does not need to turn every step into an offer or ask the player to choose it again.

## Review and memory

The existing reviewer response now has two separate expression arrays:

- `evidence`: the NPC's spoken words.
- `actions`: the NPC's performed action in narration.

Both cite exact passage IDs from the same completed reply. Their union covers the
controlled actors, with at most one entry per actor in each array. An action-only
intention requires action evidence and no invented speech. A mixed expression may
have both. An inactive silent `DEFER` retains the legacy empty speech evidence.
Unknown actors, duplicate coverage and missing or invented passages are rejected.
Attribution and consistency with the selected intention still need semantic review.

Delivered action evidence is retained separately from `spoken_evidence`. Its bounded
observer-local transcript entry is `own_action`, not heard speech or a spoken promise.
Only that actor's reviewed assistant narration qualifies. The cognitive source uses
the existing reported `narration` kind, never an authoritative world frame. Physical
effects still pass through their existing state owners; reviewing an intention's
expression cannot create an item or bypass a rejected world update.

Previous-action continuity requires the original retained message, revision, hash,
actor and source kind. Input packing can omit older action excerpts from the view;
it does not delete canonical memory. Copy/import rebind source IDs through the
existing lifecycle; edits and rewind invalidate dependent evidence. Legacy saved
decisions and reviewer replies default to no action evidence. No persisted schema
version change, new inference request, approval dialog or independent state store
is introduced.

### Movement result feedback

The movement owner now emits bounded receipts for source-valid proposals. Each
receipt binds the exact assistant message, revision, hash and text occurrence;
it contains only an actor ID, cited movement and `applied`, `blocked` or
`unconfirmed`. It does not expose private rule reasons or prescribe a next action.
Only a concrete access/capability denial is `blocked`. Invalid, ambiguous or
stale proposals are `unconfirmed`, not fictional failed attempts.

The reviewer preserves the selected passage's offsets, including repeated words.
The original action quote remains unchanged. Its qualification travels with short
memory, the retained narration source, previous-intention context, appraisal and
agent memory reads. Tool and semantic pin producers charge the qualification to
the same evidence budget. Fallback recovery retains the receipts on its existing
source-bound audit so later catch-up does not lose them after another turn replaces
the current diagnostics. Copy and retraction follow the original source.

Optional causal updates and completed-frame observations cannot certify a cited
blocked or unconfirmed movement. If a causal passage combines independent effects
with that movement, the optional update is conservatively deferred; existing
threads, valid world mutations and speech remain. Separating those effects more
finely requires better evidence. No extra model request or late prose rewrite is
introduced, so an inconsistent original narration may still be visible beside the
existing state-review notice.

Receipts cover movement proposals with usable source evidence. An omitted section,
whole extraction failure, oversized batch, invalid citation or absent receipt does
not certify completion. This change does not repair semantic omissions or extend
authoritative receipts to every item, condition and staging operation. Current
host state remains authoritative. Choice policy is unchanged: waiting, refusal,
an alternative or action can all be reasonable when grounded in the NPC's motives
and available evidence.

## Scope and verification

The foreground VN turn supports the existing state domains in Personality off,
shadow and live modes. Optional background Living World scheduling retains its own
bounded action contracts and clocks; this change does not replace that simulator.

Offline regressions exercise nonverbal and mixed expressions, exact citations,
speech-only commitments, private observer memory, source invalidation, copying,
input budgets and actual saved turns. They include self-directed clothing removal,
placement and travel, with the player's inventory and location unchanged. Locked
routes remain blocked. These checks verify host behavior and prompt delivery;
they do not measure a live model's initiative or semantic reliability.
