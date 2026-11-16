# Planned world features

The current priority is fixing existing behavior and validating a stability release.
These ideas are a backlog, not features included in that release. Before each change,
trace its existing implementation, configuration gates and lifecycle tests, then
extend its current owner wherever possible.

1. **Evolving item state.** Preserve an item's ID, ownership and history as a container
   becomes filled, a blank sheet becomes written or a matchbox becomes empty. Reuse
   the physical-condition ledger for supported facts; inspect the gaps for contents,
   quantities and consumed components before choosing a data-contract extension.
   This is the first candidate after the current bug fixes.
2. **Emergent NPC registration.** Extend existing character discovery and learning
   when a newly encountered character becomes more fully described. Reuse its stable
   identity and distinguish self-reported information from confirmed world facts.
3. **Coherent NPC rotation.** Extend Living World/Concordia scheduling so a growing
   cast does not require analyzing every NPC each turn. Departures, absence and return
   must preserve identity and have supported world explanations. Off-screen progress
   and new possessions need explicit provenance rather than invented gap-filling.
4. **User-authored world rules.** Audit and adapt upstream script support for opt-in
   triggers, conditions and actions. Examples include a periodic world event changing
   traits, timed character conditions and a seeded random outcome when entering a
   doorway. Use existing clocks, script boundaries and rollback mechanisms.
5. **Additional world knowledge.** Import source-attributed lore into the session's
   existing RAG memory with clear world/session scope and separation from canonical
   outcomes already established in play.
6. **Fact dependency viewer.** A small star button opens a read-only view of facts,
   sources and their relationships, reusing existing evidence and causal lineage.
7. **Reference-driven world generation.** Accept source URLs and configurable depth
   and size limits when collecting history, locations, characters, clothing, goals
   and items. Show progress and warn before a detailed world may take hours to build.
   Inspect existing generation jobs and recovery before introducing another pipeline.
8. **Character LoRA selection.** Allow NPC and player cards to select an installed
   LoRA file for compatible ComfyUI workflows. Extend existing presets and loader
   handling; define how multiple depicted characters and unsupported workflows work.
9. **Catalogue compatibility and example worlds.** Audit remaining upstream catalogue
   differences, complete compatibility and provide two or three distributable example
   worlds with different sizes and levels of detail. Keep public descriptions neutral.

Automatic NPC creation, rotation, scripts, lore import, graph UI, reference-driven
generation, character LoRAs and catalogue expansion remain planned work. The item
state proposal also needs an existing-functionality audit before implementation.
