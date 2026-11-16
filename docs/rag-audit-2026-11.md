# RAG audit and implemented corrections

Scope: public session recall and optional observer-scoped NPC Personality recall.
Canonical SQL history, source-bound psychology and current inventory/clothing
remain authoritative. No live or paid model requests were used for these fixes.

## Findings addressed

| Finding | Correction |
| --- | --- |
| A relevant phrase near a chunk's end vanished in the final prompt | Select an exact, query-focused excerpt and preserve its document offsets |
| Same wording from separate scenes was deduplicated | Deduplicate source instances, retain scene and source-message references |
| A large cast divided category space into unusably small pieces | Share unused category space inside the unchanged 2,500-character total |
| An empty projected RAG block could replace useful legacy context | Require an actually projectable result before replacing legacy recall |
| Scene/cast changes reused stale SQL ranking | Refresh selection while reusing the turn's original vector request |
| Embedding models could not receive distinct query/document instructions | Add exact, configurable prefixes; include nonempty prefixes in the vector signature |
| A slow embedding server could stall foreground recall for its full service timeout | Bound foreground embedding/search and use lexical fallback |
| SQLite's built-in case folding missed old Cyrillic mentions | Register Unicode-aware bound search; normalize each transcript row once |
| Alphabetic query-term truncation could lose the player's main term | Preserve query order when selecting bounded lexical terms |
| Repeated summaries or provider failure starved indexing | Rotate independent maintenance phases with per-phase backoff |
| CHPM observer search used only matching words | Add opt-in hybrid recall over each observer's saved sources |
| Public generation cleanup would erase a separate observer signature | Partition queries, upserts and pruning by namespace; clear both only on owner-scoped operations |
| The vector hash catalogue silently stopped after 100,000 rows | Page through the complete catalogue |

Regression tests demonstrate the original public-context, embedding-protocol,
maintenance-fairness and namespace-overwrite failures before their fixes.
See [memory setup](memory-rag.md) and [semantic NPC memory](chpm-semantic-memory.md).

## Architectural assessment

The existing SQL authority, owner/session isolation, source hashes, timeline
epochs, hybrid ranking and rebuildable vector cache are sound foundations. The
largest corrected losses were between retrieval and final context construction,
and in maintenance scheduling; increasing context alone would not repair them.

For repetitive RP, retain source identity, speaker/observer, place and order
through the complete pipeline. Vector similarity is a candidate generator.
Exact source validation and current canonical state decide what may be used.
Observer knowledge must be filtered before retrieval, not merely described in
instructions after unrelated memories have entered the prompt.

Semantic recall does not implement a general causal world simulator, body-state
ledger, information transmission between distant NPCs, or automatic inference
that an object caused a political consequence. Existing causal continuity records
explicit source-backed links; those broader systems require separate design and
evaluation. No new generative requests were added to conceal these limitations.

## Further evaluation

Build a source-ID gold set from repeated scenes, changed ownership, similar objects
and multilingual paraphrases. Measure correct-episode recall, wrong-observer
exposure, stale-source rejection, final-prompt evidence retention, latency and
embedding volume. Assess retrieval separately from whether the narrative model
actually respects the supplied evidence and character psychology.

The new tests use deterministic embeddings and real local storage, not a live
semantic-quality benchmark. Full model context size alone does not establish
effective attention, recall quality or psychological consistency.

## Research references

- [Microsoft: design and evaluate a RAG solution](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-solution-design-and-evaluation-guide)
- [Microsoft: hybrid search and reciprocal rank fusion](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking)
- [Microsoft: chunking strategies](https://learn.microsoft.com/en-us/azure/search/vector-search-how-to-chunk-documents)
- [Microsoft: vector filters](https://learn.microsoft.com/en-us/azure/search/vector-search-filters)
- [GraphRAG: local search](https://microsoft.github.io/graphrag/query/local_search/)
- [Lost in the Middle](https://aclanthology.org/2024.tacl-1.9/)
- [LongMemEval](https://arxiv.org/abs/2410.10813)
- [Anthropic: contextual retrieval](https://www.anthropic.com/research/contextual-retrieval)
