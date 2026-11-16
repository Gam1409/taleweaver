# World features: current foundations and remaining work

This is a scope map, not a promise that every idea below is implemented or a fixed
release order. Before extending a feature, trace its current owner, configuration
gates, source provenance and lifecycle tests. Reuse that owner rather than adding
another state ledger or extraction request.

## Foundations already available

- **Evolving item state:** [item identity and current properties](item-state.md),
  [clothing and placement reconciliation](narrated-item-reconciliation.md) and
  [persistent physical conditions](persistent-physical-state.md) retain canonical
  IDs and separate ownership, placement, wear and condition. They do not guarantee
  correct interpretation of every narrative paraphrase.
- **Encountered characters:** [NPC introductions and learned cards](npc-introductions.md)
  resolve supported identities, retain attributed facts and expose current state.
  This is not unrestricted automatic creation of any person mentioned in prose.
- **Cast focus and scheduling:** [Living World](living-world-usage.md),
  [larger CHPM casts](chpm-large-casts.md) and [NPC presence](engineering/npc-presence.md)
  provide bounded scheduling, focus and absence/return state. They do not prove
  that every off-screen action or return has a coherent narrative explanation.
- **Authored mechanics:** the [scripting engine](scripting_engine.md) provides
  restricted adventure hooks and deterministic rules in supported modes. Parsing
  or importing a script does not make every upstream API available or enable RPG
  scripts in VN mode.
- **Additional world knowledge:** [World Info](session-world-info.md) imports and
  reviews session-owned facts, with source attribution, groups, tags and bounded
  [RAG recall](memory-rag.md). It is mutable session knowledge, not an adventure
  template or automatically resolved portable authored corpus.
- **Community adventures:** the [catalog and compatibility adapter](adventure-catalog.md)
  install supported stories and prepare original-project exports. Feature checks
  still reject unsupported behavior; a recognized envelope version alone is not
  a compatibility guarantee.

## Remaining design and evaluation

1. **Richer item contents and quantities.** Audit supported properties and
   condition facts before adding quantities, nested contents or consumed-component
   semantics. Preserve identity, ownership and source-backed changes.
2. **Broader character discovery and coherent rotation.** Extend supported
   discovery when a new character is described without a clear introduction.
   Keep stable identities and claimed/observed attribution. Off-screen progress,
   new possessions and returns require supported events rather than gap-filling.
3. **Further upstream rule compatibility.** Audit unsupported hooks and APIs
   individually. Use existing clocks, sandbox, changesets and rollback boundaries;
   compatibility must include failure and mode-specific execution tests.
4. **Fact dependency viewer.** A read-only view could expose sources, relationships
   and causal lineage through existing evidence. Graph navigation must not create
   causal links from similarity or shared wording.
5. **Reference-driven world generation.** Source URLs, collection depth, asset
   bounds and progress reporting could extend existing generation/recovery jobs.
   Importing World Info alone does not generate an adventure or a population.
6. **Character LoRA and reference pipeline.** Character-card selection of installed
   LoRAs, consistent portrait/sprite variants and multi-character illustrations need
   checkpoint/workflow compatibility, identity checks and measured visual results.
   Existing ComfyUI presets and reference inputs are foundations, not a guarantee
   of unchanged anatomy, outfit details or framing across models.
7. **Catalogue coverage and distributable examples.** Continue testing remaining
   upstream differences and example worlds of different sizes. Preserve source
   authorship and asset licenses; keep public descriptions neutral.

Source-valid host transitions, model understanding, literary quality and visual
consistency require different checks. Passing a mocked integration test does not
establish all four.
