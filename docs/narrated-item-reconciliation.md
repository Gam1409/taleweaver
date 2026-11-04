# Completed narration and possessions

VN turns reconcile item actions after completed narration and before scene staging and illustration snapshots. This adds one bounded Small-role request (up to 60 seconds); streaming text remains available while the final state is checked. Incomplete narration is never used. Guardrail rejection and canonical possession rejection block reconciliation; failures produce a system notification rather than claiming inventory was updated.

Existing items retain IDs and gameplay metadata. Transfers remove the previous owner's inventory, worn reference and equipment reference, then update the recipient. Receiving or holding does not equip the item. Wearing needs existing appearance and valid garment metadata. Each action is validated against copies before any changes are stored. Reprocessing the same input message is a no-op.

An explicitly established ordinary object or garment without a canonical ID can become an inline inventory card. The schema cannot grant bonuses or effects. Descriptions must preserve known facts and leave unknown details unspecified. New underwear requires detailed clothing and an established adult source owner (or adult recipient for a scene acquisition). These gates do not infer age from prose.

Every proposal needs an exact quote from the completed response, valid participant IDs and a completed-action classification. Semantic interpretation still depends on the model: quote matching alone does not prove transfer or consent. The private `__narrated_items__` ledger stores accepted changes, rejected reasons, source input-message ID and narrative hash. Session replay/checkpoints preserve the state transactionally; newly materialized dropped objects retain runtime provenance for checkpoint cleanup. Regeneration remains a prose rewrite preserving committed outcomes, not a second transfer.

The current reconciler covers acquisitions into actor inventories, actor-to-actor transfers, removal and wearing. Scene drops, consumption, locked-container access and gameplay rewards continue through the existing mechanics pipeline. Existing past messages are not retrospectively mined for possessions. Inline cards do not require image generation.

The pre-narration clothing planner can also use the latest completed same-scene narration as evidence that a present giver has a previously described garment. A current player assertion alone cannot establish that source.
