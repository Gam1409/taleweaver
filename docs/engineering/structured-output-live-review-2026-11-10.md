# Structured output: live validation boundaries

The probes used KoboldCpp 1.124.2 with Artemis 31B Q6_K and synthetic adult
characters in an isolated test database. No private stories, server addresses,
credentials or raw responses are included here. JSON schema mode used the normal
application router and its local validation.

## Protocol and state checks

- Three ordinary protocol probes passed: a minimal schema under conflicting text,
  literal text preservation, and an operation restricted to an existing condition.
- A separate reserved-marker probe failed: this server moves `<think>...</think>`
  out of a JSON string into `reasoning_content`. Raw HTTP reproduced the alteration
  without application cleanup. The application does not guess where to reinsert it.
- Four fixed laundry/first-aid passages passed 18 checks for canonical identity,
  possession, placement, persistent contamination and wound treatment. The real
  shared extractor and persistence ran; these were not full generated story turns.
- A more demanding four-passage garment sequence passed 18 of 23 checks. It covered
  partial removal, complete removal and transfer, another transfer and basket
  placement, then washing and partial dressing. Stable identity, later ownership,
  basket placement, cleaning and persistence of a fabric tear passed.

The five failed checks were partial wear and coverage in the first passage,
recording contamination in that passage, transfer after removal in the second,
and partial coverage after dressing in the fourth. The first condition proposal
had an inexact quote and was correctly rejected. Removal and handover produced
duplicate actions for one item: the host accepted removal and rejected the later
handover. No quote checking or duplicate-action protection was weakened.

These garment probes exercise post-narration reconciliation, not the preceding
mechanics/wardrobe stage. They expose extractor and integration limits; they do
not establish the same failure rate for a complete gameplay session. Syntactically
valid output still requires correct semantics and evidence.

## Full two-NPC turn and causal commit repair

The full pipeline included semantic-memory bootstrap, mechanics, perception, two
NPC decisions, narration and review. It took approximately 227 seconds before a
host `KeyError` prevented completion. The two NPC proposal stages took roughly
52 and 49 seconds. The failed turn is not counted as a successful live turn.

The causal graph assumed every evidence record had a host source. Psychological
interpretations also create evidence, so that assumption was invalid. The repair
reads observation records from the existing chronological event ledger and keeps
interpretations and beliefs intact.

After repair, replay of the captured outputs through the actual completion method
saved both NPC decisions as delivered, retained the causal thread, and passed
serialized state validation. Replay made zero new LLM requests. It verifies this
host failure, not a new live generation or a performance improvement.

## Remaining validation

- Full gameplay testing of partial garment placement and multi-action transfers.
- Semantic accuracy of condition details and exact evidence quotes on difficult
  passages. A decoder grammar does not prove narrative truth.
- Server handling of reserved reasoning markers inside literal JSON values.
- End-to-end latency: a successful schema transport does not remove the cost of
  sequential perception, proposal, narration and review calls.
