# NPC Personality release history

NPC Personality (technical module name: CHPM) has its own release version, independent of TaleWeaver's app
version and persisted data contracts. The current version is **1.2.0**, defined
in `backend/engine/chpm/version.py` and exposed in session settings and status.

## Unreleased repairs

- Localize completed proposal rejection in Keep playing mode when a separate
  usable NPC decision survives. Reuse inactive-character restrictions and the
  shared narration review; keep strict and shared-failure rollback boundaries.
- Preserve deferred NPC psychology and exclude their new portrait thoughts and
  emotions while retaining independently reviewed peers and their display cues.
- Allow INITIATE → CONTINUE to maintain a discussion with unchanged conditions.
  Other kind changes still need grounded revision and semantic review.
- Expose bounded per-character failures and a partial status outside the story.
  Keep one shared proposal retry and the existing saved-state versions.

## 1.2.0

- Add opt-in semantic NPC memory in Enabled mode. Match paraphrases against each
  NPC's saved, witnessed or explicitly reported sources, combined with lexical
  ranking and existing source-bound causal continuity.
- Index observer sources in idle batches, isolated from public narration memory.
  One foreground embedding batch covers active interlocutors; it adds no
  generative model request and falls back to lexical recall when unavailable.
- Carry exact excerpts, scene IDs and observation order through decisions,
  narration and review. Similar wording never merges separate episodes.
- Recheck message revisions, hashes, owner, observer and index generation before
  using a hit. Editing a source invalidates its dependent history as before.
- Keep existing request and evidence budgets, original personality, and saved
  contract versions unchanged. Existing sessions load with the option disabled.

See [semantic NPC memory](chpm-semantic-memory.md) for setup, costs and limits.

## 1.1.0

- Keep source-bound causal continuity: why an unfinished task began, what already
  happened, which concrete consequences persist and what remains to be done.
- Preserve statement history and explicitly attributed influence links in the
  observer's evidence graph. Narration order alone does not establish causation.
- Pass open declared goals to narration/review even when they were not selected
  as the current motive; retain verified context during ordinary fallback.
- Reuse the existing live narration review without an additional model request.
  Bounded current views and pinned original passages share the agent's evidence
  budget. Invalid optional annotations are audited without rejecting valid RP.
- Rebind complete evidence graphs on session copies and rebuild prior thread
  states after source retraction. Original authored personality is unchanged.

This additive release keeps the existing saved schema and reducer versions.
Old conversations are not automatically reconstructed; extraction starts with
newly reviewed replies. See [causal continuity](chpm-causal-memory.md).

## 1.0.0

First optional release for Visual Novel sessions:

- Choose Standard, Observe or Enabled per session, with an active conversation
  group inside a larger character roster.
- Preserve original traits, values and goals while recording evidence-backed
  interpretations, qualitative feelings and tentative developing tendencies.
- Track witnessed quotations, declared goals and promises with source ownership.
- Let NPCs choose distinct responses and relevant questions without asking for
  generic permission to keep writing.
- Offer bounded, read-only agent lookups for an NPC's available memory,
  possessions and visible clothing layers of other present NPCs.
- Keep RP going during optional analysis failures, or choose Strict inspection.
  Simplified turns preserve confirmed psychology and disclose continuity gaps.
- Integrate session ownership, save/load, source edits, copies, checkpoints and
  recoverable turn publication with the host's existing mechanisms.
- Configure adventure defaults under the editor's Living World menu; already
  started sessions keep their own settings. Session settings have three columns.
- Inspect content controls and Concordia/Personality diagnostics from debug, and
  repair individual item text, visual metadata and images with a reviewable draft.
- Enter multiline player actions, scroll and page NPC history, and route the five
  OpenAI-compatible model roles to one shared server or separate endpoints.

The first release remains experimental: it is a character consistency tool, not
a validated simulation of human psychology. Quality and speed depend on the
chosen model. See [the player guide](chpm-continuation.md) for costs and limits.

### Compatibility

This release adds safe-default recovery and usage fields. It does not bump
`KernelState.schema_version=6`, `Snapshot.schema_version=4`, or
`transition_version=evidence-ledger-v3`. Module release versions identify product
behavior; those three contracts identify persisted data and reducer rules.
Their version numbers need not match. New readers load prior version-6 saves
without enabling CHPM. Keep a backup before downgrading to an older reader,
which may reject additional fields.

Adventure defaults add one nullable `npc_personality_settings` database column.
The normal startup migrations apply it without enabling existing sessions.
