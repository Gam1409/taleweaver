"""NPC possessions are engine state; character knowledge is a separate historical record."""

NPC_POSSESSIONS_RULES = """
NPC INVENTORY PRIVACY: NPC inventories are PRIVATE GM STATE, not player knowledge.
Opening a character card is not an in-world action and reveals no inventory.
Looking at an NPC only reveals visibly worn/held objects, not hidden pockets or bags.
For requests to see possessions, consider the NPC's motives, relationship and situation:
they may agree, refuse, lie or show only selected items. A request is not permission.
For covert searches or theft, honor the resolved outcome; a failed attempt reveals
no hidden contents and transfers nothing. In RPG mode request an appropriate skill
check for uncertain access. Never narrate success before its result is available.
Reveal only items actually seen/shown/retrieved in that encounter, from existing state.
Past sightings and gifts do not prove what the NPC carries now. A remembered possession
must not override current engine state. Do not disclose later off-screen changes.
"""

NPC_POSSESSIONS_MECHANICS = """
NPC ITEM AGENCY: A gift transfers ownership, not control over the recipient.
An NPC may accept/refuse it, keep it, put it away, wear it, use/consume it, discard it
or pass it on as justified by their own goals. Persist actual changes using existing
item IDs and supported fields; never invent new objects, effects or equipment slots.
Use NPC inventory in updated_entities with the complete remaining list, preserving
unaffected possessions. A transfer also removes the item from its previous holder.
Dropping an item uses spawned_items and removes it from the NPC. Consumption removes
it and applies only established effects. Wearing/storing an owned item retains it in
the NPC inventory and records its current use in NPC notes; it does not equip the player.
An observation, inspection, refusal or failed search alone must not change ownership.
Only the resolved, player-perceived consequences belong in narration and learned history.
"""
