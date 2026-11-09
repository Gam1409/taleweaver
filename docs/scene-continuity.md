# Scene continuity

VN turns reuse the existing completed-narration item/physical-state extraction request.
`scene_updates` proposes environment, process and environmental-effect deltas;
`final_frame_actions` describes the final visible instant. No extra summarization
request or agent framework is added.

When the existing **scene staging** session option is enabled, its pose and prop
deltas also use this same request. The `SharedItemExtraction` transport preserves
independent sections; item actions still pass the original strict `ItemExtraction`
validation before mutation. A bad item section cannot grant a placement or suppress
an independently valid pose. A bad staging section does not undo accepted item facts.
When staging is disabled, the original item response schema is used.

The existing staging registry, quote checks, invalidation and message-source stamps
remain authoritative. The narrator's staging block includes confirmed placed items
as well as poses. Worn-item candidates can be proposed for placement, but the host
rechecks eligibility after accepting removal/transfer. New items may be referenced
by their original zero-based `item_action_index`; only accepted actions can supply
an ID. Rejected placements remain diagnostic counts rather than new world facts.
The shared path never issues a second staging request after timeout or invalid JSON.

The host saves accepted deltas under `__scene_continuity__` after the assistant
message is flushed, in the same turn transaction. Each record has a canonical
subject and scene, origin/latest source quote and hash, message revision, game
minutes, visibility, witnesses and optional causal link. Unsupported candidates
are rejected independently; existing facts are preserved. These records cannot
move actors, transfer possessions, expose clothing, change HP or grant capabilities.

## Events, processes and consequences

An active process persists across dialogue-only turns and visits to other scenes.
An explicit end changes its status; associated effects remain until separately
changed or ended. A causal link must reference an existing fact and cannot form a
cycle. The host checks identifiers and evidence; the extractor still has to judge
whether the prose actually establishes the claimed state or causal relationship.
An exact quotation alone is not proof that the model understood it correctly.

When an explicit duration supplies a review horizon, reaching that **game minute**
makes the projection `needs_confirmation`. It does not invent a completed action,
heal an injury or clean a surface. Turn count and real elapsed request time do not
end processes. Historical records remain in storage when outside the current scene.

Body/garment injuries, pain, fluids and dirt remain in the existing physical-condition
ledger; clothing and possessions keep their existing authoritative registries.
Scene continuity does not duplicate those facts or replace CHPM subjective memory.
Visible physical traces use optional `visual_detail`/`visual_region` evidence in that
same ledger. The visible phrase must occur verbatim in the condition's source quote.
Image projection checks public visibility, current region coverage and visible garment
identity; it excludes private/internal states, unknown coverage and resolved conditions.
An opaque higher layer can hide a trace without healing or cleaning it. A prose edit
revokes the affected visual evidence while retaining canonical physical conditions.

## One saved state, audience-specific views

- The narrator receives current accessible public facts and player-known private
  facts, with status and game minutes, outside the recent-dialogue window.
- Live NPC Personality receives a typed, citable host frame. Public ongoing facts
  can be observed in the current scene. An ended event is not automatically known
  to a later arrival. Private facts and causes are restricted to their known observers.
- Moment snapshots freeze only public, currently visible `visual_detail`, public
  room objects/decorations and source-backed final-frame actions. The neutral visual
  planner and audit receive these as atoms with actor bindings. An old snapshot is
  never completed using later session state.

Room-only environment facts are extracted separately from authored scene prose.
This retains interior and lighting without reintroducing obsolete outfits embedded
in that prose. If extraction is unavailable, managed-clothing captures retain the
safe room label and public objects/decorations; they do not guess the missing interior.
Changing authored room text invalidates its old environment projection until refreshed.

Copy/import remaps narration sources; missing sources become unconfirmed. Editing
or replacing a response retracts its derived facts and final-frame actions. Full
turn replay restores the complete pre-turn state through the existing snapshot path.

## Bounds and verification

There are at most 12 scene deltas and 4 final-frame actions per extraction, 256
stored scene records, and 10,000 characters in a scene context projection. Full
storage rejects additional records visibly rather than discarding existing causal
history. Projections report omitted records; image snapshots select at most 16
visual scene facts. These are bounded current-state views, not an unlimited archive.

Tests use deterministic model doubles: persistence across 40 intermediate dialogue
turns with the normal 10-turn history window,
explicit process endings, surviving effects, game-time horizons, visibility,
source edits/copy/replay, capacity boundaries, old-source isolation and unchanged
request count. They do not establish live-model extraction accuracy or image quality.

Text facts do not guarantee identical room geometry across generated images.
Background/portrait reference conditioning needs a compatible reference workflow
and an explicit reference choice; this change does not silently switch text-to-image
requests to img2img or treat one background image as character identity conditioning.
