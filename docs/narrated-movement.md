# Completed narration and canonical travel

VN's progression pass still owns the initial world resolution. The existing completed-response extraction now also returns `movements`, alongside items, conditions and scene facts. This closes the gap where the narrator completed a departure or a player-authorized arrival after the progression pass, while the saved map and cast remained unchanged. It adds no model request and is independent of NPC Personality.

The host supplies nearby canonical routes, their current locks, available NPCs and effective movement permissions. Each proposal must select a completed-narration source occurrence. Player travel additionally requires exact evidence from the current saved player message; narration alone cannot authorize the player's action. Each companion needs its own proposal. Unknown destinations are not created by this mechanism.

Before committing, the host rechecks the source text and movement context. Known actor IDs, direction, adjacency, locks, mobility, authored scene restrictions and rejected-action scope remain authoritative. Ambiguous multiple final movements for one actor are rejected together; an independent valid actor can still move. Local presence changes use the existing `present` / `audible` / `absent` field, without hiding or deleting the character.

Accepted changes use `TurnStateApplier`'s existing entity movement, presence and scene-transition methods inside the current turn transaction. Inventory, rewards and elapsed time are not applied a second time. The existing turn-boundary owner handles late player arrivals and preserves already-resolved elapsed time. The assistant message's scene, journal minute, final state and illustration snapshot describe the confirmed arrival.

Scene continuity is prepared again for a confirmed arrival before its proposed final facts are committed. New room facts must name that destination; authored descriptions of the departed room cannot become destination evidence. Poses tied to the previous location remain subject to the existing scene-scoped staging checks.

The bounded `movement_check` audit lives in the existing narrated-state check, with the saved assistant ID, source hash, accepted proposals and rejection reasons. Copying remaps its message ID. Existing replay and Debug snapshots restore the ordinary canonical scene and entity overrides; there is no second movement-state store.
