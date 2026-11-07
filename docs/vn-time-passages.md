# Explicit VN time passages

Ordinary VN activity keeps its existing bounded elapsed-time estimate (at most 1,440 minutes, or the author's smaller per-turn limit). An explicit player declaration such as “Three days passed” now has a separate optional `time_passage` field in that same continuity request. It does not add a model call.

The model supplies an integer amount, minutes/hours/days/weeks, a completed/future/recalled/uncertain classification and an exact contiguous quote from the current player message. Only `basis=elapsed` with valid current-message evidence is accepted. The host computes the conversion and absolute target from the current saved clock. Three days means exactly 4,320 minutes. Neither the default one-day estimate cap nor a scene-boundary surcharge truncates or double-charges this declared duration.

Malformed fields, nonmatching evidence, future plans, recollections, uncertain skips and passages exceeding an explicitly configured adventure limit are rejected without applying a guessed duration. Other valid intent fields can continue. Custom `units` clocks do not implicitly convert calendar days into arbitrary author-defined units. One explicit passage is bounded to 365 days; longer campaigns can contain successive passages. Calendar months are not a fixed supported unit: use an explicit number of days or weeks rather than silently treating every month as 30 days.

This contract does not prove semantic understanding. A literal quote plus a model classification can still misinterpret a player's statement. Mocked tests establish arithmetic, validation and persistence; live evaluation must check recognition in the user's actual model and language.

## Living World and NPC movement

NPC Personality controls character decisions during foreground RP. It does not independently enable Living World, schedule background work or make a fixed NPC movable.

Autonomous background movement requires:

- Living World enabled and an appropriate live/catch-up mode;
- scheduled events, or recurring schedules with private decisions enabled;
- a permitted destination, a traversable connection and a movable NPC;
- for private model decisions, inference serialization and a supported utility-model connection; the Concordia engine additionally requires its optional dependency.

Background movement near a recent player interaction can be deferred so it does not interrupt that scene. An NPC may also choose to wait. There is no promise that every NPC will move after every turn.

A declared time jump advances the story clock. Living World retains due events and processes them through existing bounded batches. The target, simulation cursor, pending events and request budgets remain visible. An unfinished batch stays partial; it is not reported as a completed history. Catch-up never rewinds the story clock. An already-reconciled empty interval also cannot be rewound by an older per-request budget.

With recurring schedules disabled, empty intervals can be reconciled without inventing thousands of decisions. With recurring schedules enabled, each pending slot still needs actual processing: large skips can leave substantial work. The existing journal and timeline-wide model-call budgets remain finite and can stop simulation explicitly; this change does not implement a semantic summary or unbounded automatic simulation of months of activity. Increasing elapsed time is not permission to remove pending events, heal injuries, expire promises or fabricate NPC actions.

## Verification

Offline regressions run real saved VN turns and owned Living World API cycles for skips of 3, 30, 90 and 180 days. Both native and installed Concordia orchestration use deterministic local model responses. Two off-scene NPCs act at their original due times and move only through validated connections. Batches retain unfinished events, preserve the story clock and do not repeat completed model decisions. Additional tests cover ordinary waits, explicit limits, custom units, invalid optional JSON, future/recalled time, full-turn replay and persistent physical-state timestamps.
