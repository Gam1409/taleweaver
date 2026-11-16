# TaleWeaver v0.7.1-beta

This stability update improves continuity between narrated events, saved world state
and the information supplied to subsequent model requests. The application remains
in beta; NPC Personality and model-assisted state extraction remain experimental.

## Story context and memory

- Debug commands and their replies no longer consume the recent story-turn window
  or enter narration, planning, chronicle input and semantic memory as dialogue.
  Their saved history appears only while session Debug is enabled.
- Technical generated replies are excluded from NPC learning, its retry timers and
  Characters progress. Their tasks cannot hold a story-learning lease.
- Exact source fragments distinguish repeated wording from different events.
  Extraction diagnostics expose missing sections and rejected changes without
  discarding unrelated validated updates.
- Narrative summaries retain the meaning and established consequences of events.
  Existing history and old chronicle text are preserved rather than rewritten.

## World state and characters

- Completed, permitted narrated travel updates canonical locations and NPC presence.
- Taking a loose scene item uses effective session possession rather than stale
  template ownership.
- Repeated physical-condition proposals can resolve an unambiguous existing record
  while preserving its identity, origin and game-time timestamps.
- NPC cards combine a persistent profile, state and history tabs, layered visible
  equipment and source-backed physical facts. Debug separates worn, carried and
  room placement and provides reviewed, source-bound recovery of missing records.
- NPC decision failures are localized where compatible actions can continue.
  Optional thoughts and portrait emotions work independently of decision admission.
  Factual review preserves expressive dialogue and emotional delivery.
- Technical structured-output contracts share the existing provider router, with
  local validation and more accurate provider-error reporting.

## Debug and interface

- Detailed logging is opt-in and covers model requests, replies, engine stages and
  embedding work. Logs may contain the full session text; inspect them privately.
- Debug retains five recent before-turn states for exact rollback. Older history
  still requires an available checkpoint; missing historical snapshots cannot be
  reconstructed retroactively.
- Thought clouds have a readable font, an animated appearance and viewport-aware
  placement. Keyboard dismissal and reduced-motion preferences are supported.
- Hiding technical history does not permit regeneration or version restoration
  across a state-changing Debug command.

## Updating

Back up the complete application data profile, or the persistent Docker volumes and
existing keys, before updating. Normal startup applies the additive database
migration for the saved Debug-message flag. Existing images, story text and canonical
world corrections are retained. Adventure format and NPC Personality versions are
independent of this application version.

Native distributions include the runtime and built interface. Extract the complete
archive. Model weights and ComfyUI remain separately configured. The Windows and
macOS applications remain unsigned.

Local regressions verify host behavior with mocked models. They do not establish
that every model will extract every literary event correctly. This update does not
expand the short social-planning window or rebuild previously generated chronicles.
