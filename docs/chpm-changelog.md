# NPC Personality release history

NPC Personality (technical module name: CHPM) has its own release version, independent of TaleWeaver's app
version and persisted data contracts. The current version is **1.0.0**, defined
in `backend/engine/chpm/version.py` and exposed in session settings and status.

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
