# Session content language (experimental)

Choose a language using the in-game Babel Fish selector. The choice is now saved
on the server for this session. Reloading or opening another device restores it;
other sessions retain their own choices. Pause the Play-Agent and finish the
current turn before changing language.

On first access, existing sessions without a choice use the profile's default
language, then the adventure language, then English. This resolved default is
saved. **Use default** resolves and saves that preference again. The previous
browser-only preference no longer overrides the server. Local storage only
mirrors the current language for audio playback.

## First-stage coverage

- New storyteller narration, dialogue, combat narration and closing epilogues.
- Action ideas, including explicit `/shuffle` requests. Changing language replaces
  stale ideas immediately with offline suggestions; shuffling generates contextual
  suggestions in the selected language.
- Play-Agent natural-language actions and thoughts; its subsequent game turns
  resolve the same saved language.
- Offline suggestion and epilogue fallbacks for all nine selector languages:
  English, German, French, Spanish, Italian, Japanese, Chinese, Russian, Portuguese.
- Session copy and `.ads` export/import preserve the choice. Restoring a gameplay
  checkpoint does not rewind the language preference; old suggestions are replaced
  when the session snapshot reloads.

The existing UI labels, system notifications, stored world descriptions, opening
text, quest descriptions and English internal memories are unchanged. This is not
a translation of an existing world. Text-log translation remains available via
its existing button. Original entity names and speaker identifiers are preserved
so portraits, commands and game objects keep their identity.

## Technical contract

`PATCH /api/adventures/{session_id}/content-language` accepts
`{"language":"Russian"}` (or `"ru"`, `"ru-RU"`) and returns the canonical language
name plus replacement `prompt_suggestions`. An empty string resets to the current
profile/world default. Unknown languages and instruction-like input are rejected.
Only the session owner can change this setting.

`GET /api/adventures/{session_id}/chat` includes `language`. The old optional
`language` argument on chat and epilogue requests remains a per-request override;
normal UI requests use the persisted server choice.

A shared, scoped prompt requires prose in the selected language while preserving
JSON keys, IDs, enum values, effect tokens such as `Poisoned`, commands, unlock
codes, expressions, scripts and voice tags. The mechanics pass does not receive
this prose-language instruction. Existing schema validation remains in place.
A model can still ignore instructions: this stage fixes language propagation,
not multilingual model quality. It does not translate or normalize arbitrary
mechanical strings produced by the model.

The nullable `game_sessions.content_language` column is added by Alembic revision
`e70ab891c79f`. Normal backend startup applies the migration. Existing rows are
initialized lazily. The migration is reversible; downgrading removes the saved
language preference, not gameplay content.

## Manual trial

1. Open an English adventure and select Russian using Babel Fish.
2. Inspect Ideas, then regenerate them. Make a move and check narration and dialogue.
3. Reload, reopen the session, and verify that Russian remains selected.
4. Switch to Spanish or Japanese and repeat. Open a second session to check isolation.
5. Enable the Play-Agent after selecting a language; inspect its next action and narration.
6. Compare inventory IDs, effects, locks and quest outcomes before and after language changes.
7. Simulate a failed settings request: the UI should report it and retain the prior choice.

Automated tests use mocked models and an isolated database. Live multilingual
quality testing with the user's models is still needed before merging into main.

## Validation on the experimental branch

- Backend regression selection: 242 passed, three failed. The same three tests
  fail on the unmodified base commit `f0c3e21`: the consumable import, readable
  inventory snapshot and manifest starting-scene fixtures are rejected as legacy
  adventures. These failures precede this change.
- Additional copy/checkpoint language regression: one passed (243 passing checks
  in total, including 28 new language cases).
- Production frontend build passed. `vue-tsc --noEmit` reports the same diagnostic
  set as the unmodified base; no new diagnostics were introduced.
- New Python modules, migration and tests pass Ruff check and format check.
  Checking every touched module still reports existing lint findings in
  `sessions.py`, `session_importer.py` and `turn_adventure_gen.py`, plus existing
  formatting differences in the first two. Comparison with the base found no new
  lint findings; broad unrelated reformatting/refactoring was excluded.
- Alembic upgrade/downgrade/upgrade on a temporary database preserved an existing
  session and initialized its new language column to NULL.
- Chromium against the production build and an isolated API/database passed:
  repeated Russian/Spanish/Japanese selection, reload persistence, Russian Ideas,
  stale local-storage preference handling, separate-session isolation and an
  injected HTTP 503 during save. No browser runtime errors were observed.
