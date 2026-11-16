# NPC observable state tools

In **Session settings → NPC Personality**, choose **Enabled** and at least one
**Agent tool round per active NPC**. `inspect_entity` is available with or without
private notebooks. Staged and Integrated use the same read-only projection;
native function calls and JSON compatibility retain the existing request limits.
Staged without notebooks uses its legacy JSON planner; the selected native/JSON
memory port applies to notebook-enabled Staged and to Integrated operation.

## Read a current entity

`inspect_entity(argument="EXISTING_ID")` reads an exact accessible actor or item ID.
The bounded `observable_entities` index supplies IDs, names and kinds before tool
selection. It prioritizes the observer and owned items. The player uses the
existing CHPM alias `@player`. No fuzzy match creates or renames an item.

The view includes the following where known:

- Canonical item identity and inventory owner.
- Known wear state and confirmed physical placement, kept separate from ownership.
- Current recorded conditions and their existing IDs, kinds, properties and statuses.
- Visible clothing and confirmed surface conditions of another present actor.

The observer can read its own conditions and possessions. Other characters' bags,
covered clothing, private conditions, thoughts and notebooks remain unavailable.
Public room objects use the existing discovery and scene gates. A fixed object
can be observed without becoming portable or transferable. Public placed objects
retain their established owner when placed on a bench or elsewhere in the room.
Raw biographies, object descriptions, scripts and arbitrary extension metadata are
not copied into these views.

## Freshness and bounds

This is a snapshot prepared before the NPC decision, not a live database browser.
It is bound to the session, observer, input message, revision, content hash and
scene. A stale or inaccessible view returns `unavailable_entity` with corrective
feedback. That result never proves that the object does not exist or permits
registering a replacement item.

The index contains at most 32 entries within 1,500 serialized characters; omitted
entries are counted. An entity view fits 2,000 characters, with explicit counts
for omitted condition or clothing rows. Unknown, unavailable and omitted state
does not establish an empty container, repaired garment or healthy body. A
resolved own condition retains its status without repeating its old description.

Reads share the existing eight-source / 6,000-character evidence budget, up to two
operations per configured round and at most three rounds. They do not raise input
or call limits and do not add an obligatory model request. Models choose whether
to use a round; each invoked round still costs a model call. With rounds disabled,
the projection is not prepared. Personal notebook settings are unchanged.

## Decisions and state updates

Successful reads become observer-local citable sources. The same exact result is
available to the validated proposal, narrator and reviewer. It does not mutate
world state, reserve an item, complete an action or grant ownership. It is not a
new source of truth or a separate item-history store.

The shared post-narration extractor already receives canonical item IDs, owners,
clothing and physical-condition records. It continues using those current facts;
no second extraction call or duplicate state block was added. Existing session
mutation leases and domain validators retain authority over effects. Two actors
reading the same item do not acquire permission for contradictory ownership.

Views are transient. Only accepted citable evidence follows the existing mind
publication, copy/import and replay rules. Failed or cancelled turns publish no
new observer evidence. No persisted schema version or database migration changes.

## Verification

Offline tests exercise exact IDs, current mutable properties, visibility,
ownership, fixed objects, placement, missing state, bounded views and stale
anchors. Real VN turns cover both workflows, native and JSON tools, notebooks
enabled/disabled, evidence handoff, shared reconciliation and rollback. These
checks establish host contracts; live-model use and a reduction in rejection rate
still require matched live sessions.
