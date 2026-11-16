# World-builder syntax

Use structured tags in **Story Idea & Context** when an adventure needs specific
places, characters, objects or relationships between them. Free prose remains
valid. Tags constrain the generated data; they do not guarantee prose quality or
choose the player's future actions.

For an open-ended premise, history and reference excerpts, start with
[World blueprints](world-blueprints.md). Generation uses the existing
[staged world pipeline](staged-world-generation.md) and validates its output before
writing the playable world.

## Entities and fields

```text
A mystery in a coastal observatory.

[Scene: OBSERVATORY] Rooftop observatory
description: ~A quiet laboratory above the harbour.

[NPC: MIRA] Mira
in: OBSERVATORY
age: 28
gender: female
goal: Protect her research and decide whom she can trust.
character: Independent and observant; values evidence.

[Item: NOTEBOOK] Research notebook
in: OBSERVATORY
description: ?
```

- `field: value` is fixed author input, checked and reapplied during generation.
- `field: ~suggestion` guides the model without fixing the final value.
- `field: ?` leaves that field open for generation.
- Multi-line fields use `field: |` with indented lines or a fenced block.
- Structured fields such as `clothing`, `visual_profile` and `personality_profile`
  use JSON. Reference lists such as `inventory` also accept comma-separated IDs.

Use technical IDs beginning with an ASCII letter, followed by letters, digits or
underscores, up to 64 characters. Keep them unique across the planned world.
Names and descriptions can use the adventure's content language. These symbolic
references are separate from [storage UUIDs](storage-identifiers.md).

An NPC's `in` refers to a declared scene. Inventory references must name declared
items and cannot give the same item to two owners. Declare routes with
`[Exit: A -> B]` or `[Exit: A <-> B]`, where `A` and `B` are declared scene IDs.
Markdown headings such as `## NPC: MIRA — Mira` are supported too.

The grammar also recognizes world/protagonist, container, readable, switch,
weapon, sequence/chapter, quest, award, ability, talent, rule and script blocks.
The selected game mode and generation switches still control which categories
are available. Parsing a tag does not enable a disabled feature or execute a script.

## Sequences and builder mode

```text
[Sequence: 1] Arrival at the observatory
Establish the missing research and the people with conflicting interests.

[Sequence: 2] The harbour records
Offer clues that connect the observatory to the harbour.
```

The parser accepts at most 15 sequence declarations, warns about extras and ignores
them. Staged plans also cap their sequence list at 15.

**Strict Adherence** keeps fixed author requirements. **Creative Expansion** allows
the generator to develop guidance while retaining required facts and references.
Neither setting guarantees every generated sentence or forces the player's choice.
Where the chosen mode supports progression, sequence order and completion gates
use its normal mechanics. Visual Novel deliberately omits RPG completion gates;
prose sequence outlines can provide themes without turning a VN into a fixed plot.

## Check before generation

**Check blueprint** reports syntax, fields, references and configuration issues
with source line numbers. It makes no model call. Server-side generation repeats
preflight and validates the planned IDs, topology, ownership and fixed requirements
before accepting stages. Unsupported or conflicting requirements need correction;
they are not silently converted into successful world facts.

The parser lives in `backend/engine/blueprint/`; plan and batch validation live in
`backend/engine/staged_world/`. Field definitions follow this fork's schemas rather
than promising compatibility with every newer upstream scripting feature.
