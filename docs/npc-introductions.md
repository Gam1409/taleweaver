# Characters introduced during play

When a physically present NPC gives their own name in a new narration, TaleWeaver can
create a character card for that session. For example, `The girl says, "My name is Mira"`
qualifies; a narrator mentioning Mira, a player asking about her, or a letter signed
by her does not. An existing character keeps their ID when they reveal another name.
An ambiguous identity is skipped rather than merged by guesswork.

## Playing

Open **Characters** in the game toolbar to see recorded characters. Select one to open
their portrait and learned history. New NPCs receive a server-generated UUID; their
names can use any language. Existing authored NPCs remain usable as before.

After each completed response, the configured **Small / Utility** LLM extracts new
information in the session's content language. This runs in the background and does
not delay the player's next action. The journal stores appearance, background,
relationships, belongings, equipment and events, each with a source passage.
**Claim** records what a character said; **Observed** records what the narration
directly established. Neither category reveals hidden template information.

The first portrait is requested automatically through the existing image provider
and workflow settings. Its failure does not remove the card or learned information.
Use **Generate portrait** to retry. Later portraits use learned visible appearance
and equipment. They are not regenerated after every new fact.

The journal remembers described belongings and witnessed item gains/losses. It does
not create transferable loot, invent combat statistics, or assign numerical
relationship scores. **Cards never show a live inventory**, even for previously
seen items. A player can remember giving someone a cloak without knowing whether
they still own it. Hidden inventory changes do not update learned history.
Ordinary scene payloads also omit NPC inventory, equipment data and private notes;
NPC-owned objects do not appear as loose scene loot. Authoring, debug and complete
save exports retain engine data for their existing purposes.
New characters start without combat stats and are not attackable or killable.

An NPC can agree, refuse or partially comply with an in-world request to show their
belongings. Covert searches/theft use the game pipeline and, in RPG mode, its skill
checks. Prompts require respecting consent and resolved outcomes and recording only
what the player character learned. These are model instructions, not a new deterministic
authorization/stealing system: the existing skill-check schema has no per-item binding
between a roll and a transfer. Reliable conditional theft needs that engine extension.

Gifts, storage, use/consumption, wearing, dropping and onward transfers must preserve
the real inventory state and stable item IDs. Wearing/storing is currently represented
by NPC notes while the item stays in their inventory; NPC equipment slots and automatic
equipment-derived stats are not implemented here. The latest learned status of an item
supersedes older appearance/equipment observations in prompt memory, while the journal
retains the history. A discarded cloak is therefore not reused as the latest outfit.

## Persistence and recovery

- Knowledge belongs to the saved session; the original adventure template is unchanged.
- Copying or exporting/importing a save retains cards and history and remaps message
  references to the copied conversation.
- Restoring a checkpoint removes later introductions, facts and aliases.
- Opening a session or the Characters directory resumes pending learning. A failed
  response pauses later learning to preserve story order. **Retry learning** retries
  it after the Small / Utility model is available again.
- Existing conversations are **not** rescanned automatically. For an NPC mentioned
  only in old messages, have them introduce themselves in a new turn.

## Implementation and limits

`backend/engine/npc_journal/` owns extraction, evidence validation, persistence,
portraits and save lifecycle handling. `session_npcs.py` exposes owner-checked
directory, detail and retry endpoints. `ChatMessage.npc_journal` is an optional JSON
task record added by migration `f81c9d2a4b60`; character knowledge lives in the existing
session entity's metadata. Standard startup applies the migration.

Requests are limited to eight characters and twelve observations per character.
The server verifies source quotes, session ownership, existing IDs, the self-declared
name and duplicate entries before saving. **Recognizing who is speaking and whether
an introduction really occurred still depends on the LLM.** A quote check alone
cannot prove that semantic interpretation. No live-model accuracy claim is made.

The complete journal is retained; future narration receives bounded recent facts
per character, prioritizing the latest value of each category/topic. Extraction uses
up to 24,000 characters of current narration and up to 3,000 of the previous player
message. Extremely long responses may therefore leave later passages unprocessed.

Learning has a 90-second timeout, up to three recovery attempts for interrupted work,
and one worker per session. Process-wide limits allow two learning jobs and one
automatic portrait at a time. This implementation assumes a **single backend process**;
multiple application workers would need database leases. Interrupted image requests
require manual retry to avoid automatically submitting another paid generation.

## Verification

- Broad backend run: 285 passed; three adventure-format tests also fail identically
  on unchanged `main` (`45f0667`). They concern legacy adventure startup, not journals.
- Final focused journal/lifecycle run: 32 passed, including timeout recovery,
  chronological processing, ownership, aliases, Unicode, hidden items, portrait
  failures, save copy/export/import, and actual checkpoint restoration.
- Inventory clarification: additional tests exercise card invariance under hidden
  inventory changes, scene/API redaction, unchanged private engine state, witnessed
  item history and real engine gift/store/drop transitions. Browser checks confirm
  even a legacy API payload containing inventory cannot display it in the card.
  The combined follow-up regression suite passed **175 tests**. Its touched legacy
  `logic.py` retains the same 37 Ruff diagnostics and existing formatting issues;
  the focused changed modules pass Ruff check/format.
- Frontend: six journal tests and 22 dialogue tests passed; production build passed.
- Chromium checks used actual Vue components with mocked HTTP/image responses:
  directory, character card, retry, source quotes, portrait regeneration, nested
  dialogs and a 390px mobile viewport.
- Alembic autogeneration confirmed the new nullable JSON column. Upgrade and
  downgrade/re-upgrade passed on an isolated database. Unrelated existing schema
  drift was excluded from the migration.
- New Python modules pass Ruff check/format. Existing diagnostics remain in legacy
  `sessions.py`, `session_importer.py` and `main.py`; no new normalized diagnostic
  was introduced. Existing formatting issues also remain in those files and
  `tests/conftest.py`. TypeScript retains the same 129 normalized baseline errors,
  with no new diagnostics.

All automated model, image and external HTTP responses were mocked. A live playtest
with the user's models is still needed to assess semantic extraction and portrait
quality.
