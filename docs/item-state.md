# Current item state

VN item reconciliation uses the existing physical ledger for mutable item properties.
The item keeps its canonical ID, intrinsic description, owner, placement and images.
No additional model request, inventory store or database migration is introduced.

## Extensible properties

`condition_updates` accepts `kind: item_state`. Its `part` is a stable property key,
using lowercase letters, digits and underscores (up to 80 characters). The vocabulary
is open: `cleanliness`, `form`, `contents`, `fill_level`, `inscription`, `supply`,
`wetness`, `temperature`, `charge` and `sharpness` are examples, not an exhaustive list.
Values remain short source excerpts rather than a fixed enumeration.

Known visible fixed objects can retain properties too. State eligibility does not
make a non-portable object transferable. Hidden, off-scene and inaccessible subjects
remain unavailable; a shadow world row does not expose an NPC's carried possession.

A flask can have `contents: water` and `fill_level: half full`; a shirt can be dirty,
slightly damp and crumpled at the same time. Each property has one active record.
`record` establishes it; `change` references its existing condition ID. Repeated
automatic records with the same item/property bind to that ID. The model must reuse
existing properties across synonyms and languages. The host cannot prove semantic
equivalence of two differently named keys.

Empty, clean, smooth and depleted are retained values. They are not missing records
or removed items. Omission does nothing. A change in one property cannot implicitly
reset another. Multiple changes to one property within a reply require unambiguous
source order. The last accepted change is current; earlier values remain in the
bounded operation history. Existing physical conditions keep their current contracts;
the model must resolve a prior trace explicitly rather than add a contradictory state.

## Sources and quantities

The completed narrator reply supplies the normal evidence. A player report can also
supply the value after the current turn resolves it under the world's rules:

- `player_evidence` selects an exact, unique excerpt of the saved current user message.
- `evidence` still selects a source occurrence in the completed narrator response
  confirming the result. Wishes, questions, hypotheticals and rejected assertions do
  not establish state. No confirmation means no update.
- The host checks both sources and retains their local message IDs and hashes.
  Understanding confirmation versus contradiction remains a model responsibility.
- Debug messages, foreign sessions and old user turns cannot supply player evidence.

Detail must be an exact excerpt of its selected evidence (320 characters maximum).
"Half full", "a little remains" and an explicitly stated count are supported. The
host performs no quantity arithmetic and never invents an unknown remainder.
These are narrative properties, not a numeric resource simulator.

Contents and remaining supplies do not create nested inventories or duplicate known
components. Independently identified items still use the existing possession and
consumption contracts. Consuming the contents does not consume their container.
New items first need canonical registration; this pass does not attach a property
to an item whose ID is only created by that same reply.

## Views and lifecycle

The existing continuity/narrator context receives current properties, explicitly
prioritized over obsolete state in original descriptions or older prose. Player
inventory/equipment and visible VN world-item tooltips show a separate Current state
section above the unchanged original description. Public properties also reach visible
NPC equipment lists/popovers and items in already available container inventories.
NPC cards display the current property value, including values reported by the player,
rather than substituting the confirmation sentence. Private properties are visible on
the player's own possessions; public world projections exclude them. Transfers keep
properties attached to the item ID, including when its new owner leaves the scene.

Debug → State supports item properties, manual corrections, source inspection and
recent property history. Manual edits use `change` even for empty or clean values.
The current record retains first-recorded and last-changed game minutes; confirming
the same value does not restart the change clock. Recording never advances time.

Properties share `entity_states.__physical_conditions__` version 1. Additive optional
event details and player provenance preserve legacy loading. Copy/export/import remap
both source messages, marking missing sources unavailable. Reload and full-turn replay
preserve or restore the item and ledger together. Narration-only rewriting retains
world state, as it does for ownership.

Existing bounds remain: 12 proposals per reply, 512 active records and 128 recent
operation events shared with physical conditions. Older events are counted as archived;
this is not an unbounded history. Invalid evidence, inaccessible items, bad keys or
capacity failures retain confirmed facts and appear in the existing diagnostics.

Automated checks exercise host behavior with model doubles. They do not establish
live extraction accuracy, universal synonym matching or understanding of every prose form.
