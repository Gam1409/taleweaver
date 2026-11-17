# Completed narration and canonical travel

VN's progression pass still owns the initial world resolution. The existing completed-response extraction now also returns `movements`, alongside items, conditions and scene facts. This closes the gap where the narrator completed a departure or a player-authorized arrival after the progression pass, while the saved map and cast remained unchanged. It adds no model request and is independent of NPC Personality.

The host supplies nearby canonical routes, their current locks, available NPCs and effective movement permissions. Each proposal must select a completed-narration source occurrence. Player travel additionally requires exact evidence from the current saved player message; narration alone cannot authorize the player's action. Each companion needs its own proposal. Unknown destinations are not created by this mechanism.

Before committing, the host rechecks the source text and movement context. Known actor IDs, direction, adjacency, locks, mobility, authored scene restrictions and rejected-action scope remain authoritative. Ambiguous multiple final movements for one actor are rejected together; an independent valid actor can still move. Local presence changes use the existing `present` / `audible` / `absent` field, without hiding or deleting the character.

Accepted changes use `TurnStateApplier`'s existing entity movement, presence and scene-transition methods inside the current turn transaction. Inventory, rewards and elapsed time are not applied a second time. The existing turn-boundary owner handles late player arrivals and preserves already-resolved elapsed time. The assistant message's scene, journal minute, final state and illustration snapshot describe the confirmed arrival.

Scene continuity is prepared again for a confirmed arrival before its proposed final facts are committed. New room facts must name that destination; authored descriptions of the departed room cannot become destination evidence. Poses tied to the previous location remain subject to the existing scene-scoped staging checks.

The bounded `movement_check` audit lives in the existing narrated-state check, with the saved assistant ID, source hash, accepted proposals and rejection reasons. Copying remaps its message ID. Existing replay and Debug snapshots restore the ordinary canonical scene and entity overrides; there is no second movement-state store.

## VN progression recovery

The earlier VN continuity request can also recover a missed movement from the latest completed assistant response. Its NPC travel, local presence and position proposals carry an optional VN-only `movement_source`: a source kind, a supplied passage reference and a basis. The host freezes the previous narration and current saved player input before the request, exposing at most 16 passages and 4,000 characters per source. `history:pN` and `player:pN` are disjoint namespaces; offsets are resolved by the host. After the request, the host rechecks session, message identity, revision, hash and the exact selected occurrence.

Historical `completed` proposals request a new validation by the existing movement owner. An earlier `unconfirmed` receipt does not establish fictional failure and may resolve after valid revalidation. A source-bound `blocked` receipt cannot become a past success when a route later opens. Revalidation changes current canonical state without rewriting the old transcript or pretending its original check succeeded. Current player-caused physical effects use `current_player_action` with `resolved_external_effect`; a request for voluntary NPC cooperation, an intention, an attempt or a quotation alone does not supply that resolution. The existing world request classifies this distinction; no additional extraction request or keyword classifier is introduced.

For live-controlled NPCs, historical recovery additionally requires a matching reviewed own-action occurrence or the existing source-bound simplified/fallback audit. Public historical catch-up narration is not a selected own action. Legacy simplified-reply diagnostics remain usable while retained. An unaudited legacy response cannot prove who controlled the character at source time when live control is enabled later; it remains pending review. Ordinary off-mode recovery retains the existing narrator ownership.

Before the single world-event application, the adapter uses the shared movement validator for available actors, mobility, permitted scenes, oriented adjacency and effective locks, including already validated same-turn exit updates. Accepted exit changes synchronize matching existing lock overrides. Derived-map presentation failures cannot discard the canonical unlock; critical database failures propagate to existing turn recovery. Unlock notices, scripts and authored text keep their existing order and execution policy. Story departures retain their own controller gate and receive the same route check. The existing eight-actor movement bound applies. Player travel, item/object owners, RPG and Living World event schemas retain their contracts. Proof fields do not enter persisted `GameEvent` data.

Unsupported, stale, ambiguous or blocked physical proposals retain canonical location and presence and produce an explicit review notice. Coupled notes for that actor are withheld; independent actor updates and unrelated structured fields retain their normal checks. The narrator receives a retained-state reminder without an invented failed attempt or obstacle. Replay restores ordinary world state and rebuilds transient source snapshots. Deterministic tests cover these boundaries; they do not establish live-model semantic reliability.

Source-unqualified narrator companion choices may share the player's separately
confirmed current traversal. This is a new current world-plan choice, not proof of
a past departure. The host binds it to the unchanged saved player input, confirmed
origin/destination and the proposed companions; the same route and mobility checks
still apply. It cannot move a live-controlled NPC, infer an unproposed companion,
transfer a player to follow an NPC, or bypass an unconfirmed player transition.
An explicitly supplied source, including an invalid one, cannot fall back to this
compatibility path: historical claims still require their original source checks.
For a new ordinary narrator companion choice, the model omits `movement_source`
entirely instead of supplying a historical reference, forced-effect basis or null.
