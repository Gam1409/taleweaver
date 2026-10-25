# Staged world generation

World creation now plans the world first, expands it in small batches, and checks
references before writing playable world data. This is the default for both RPG
and visual-novel generation; no extra settings are required.

## Stages and context

1. **Plan:** shared plot, rules, opening, protagonist, named entity registry,
   locations, connections and initial item ownership. The first scene is the
   starting scene. All names, IDs, placements and connections are frozen after
   validation. User-requested counts and disabled categories are checked here.
2. **Details:** protagonist, then scenes, NPCs, objects, sequences, quests, awards
   and scripts. At most two entries are requested per batch. VN skips its disabled
   RPG categories. Every request uses the configured Generator role and endpoint.
3. **Integrity:** validate complete membership, IDs, references, scene reachability,
   sequence order and exclusive item ownership. Then apply the existing manifest
   and generate requested images. The existing optional validation/auto-fix pass
   still runs afterwards.

Each detail request receives the original requirements, the entire compact plan,
accepted protagonist information, accepted character facts across locations, and
relevant detailed entries. Progression and scripting stages receive all accepted
entity details. Private author knowledge remains author context; prompts explicitly
distinguish it from what the player knows. Mechanical inventory ownership comes
from the plan, independently of prose descriptions.

This design reduces output size per request, not necessarily total tokens or total
latency. Repeated context and extra requests can increase overall time. Narrative
consistency still depends on the model: structural checks cannot prove every prose
statement agrees. Large worlds still need sufficient input context and enough
output budget for their compact plan. The plan uses the configured output budget;
detail requests use at most 3,072 tokens, or the configured budget if lower.

## Failure and resume

Validated stages are persisted in `AdventureTemplate.generation_checkpoint`,
separately from `original_manifest`. The latter remains the final world. A timeout
or invalid response does not discard accepted stages. Invalid structured stage
output gets one correction attempt; transport failures are surfaced without
silently restarting the entire world.

Open the failed/cancelled world's progress window and choose **Resume generation**.
The saved request is reused with the same adventure/session. The failed stage uses
current Generator settings, so the endpoint, model or timeout can be changed first.
Repeated clicks cannot launch duplicate attempts. Cancelled/replaced workers are
fenced from checkpoint writes. Cancellation closes the local task; whether remote
inference stops immediately depends on the model server.

Changed generation inputs invalidate old checkpoints. Invalid saved details are
revalidated and regenerated; an invalid plan invalidates all dependent details.
The new checkpoint/request fields are internal and are not part of `.ads` exports.
Older failed adventures without a saved generation request cannot resume.

Retries after manifest/image application reuse the validated text stages and
reapply the world. Image work may repeat; images are not individually checkpointed
by this feature. Already played adventures cannot be regenerated through Resume.

## Deployment and verification

Run the normal database migration (`alembic upgrade head`) before starting the
updated backend. Revision `43e51d8b2a06` adds the request, checkpoint and attempt ID.
A successful initial generation now refreshes its session manifest snapshot;
unfinished snapshots no longer claim `Ready` unconditionally.
The legacy-format check also recognizes that VN deliberately has no RPG sequences;
their absence alone no longer marks a VN session outdated. Explicit older format
versions still require the normal migration path.

Regression coverage includes interrupted-stage recovery, changed inputs, malformed
cached stages, invalid IDs, cross-location context, ownership, cancellation/write
races, owner-only resume, duplicate requests and the adventure import/export
lifecycle. Automated tests mock external LLM and image services. Real-provider
quality and speed need separate evaluation on representative worlds.
