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

## Coverage

The saved selector supports Arabic, Chinese (Simplified and Traditional), English,
French, German, Italian, Japanese, Korean, Portuguese, Russian and Spanish. Names
and locale aliases are normalized by `backend/core/content_language.py`.

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

Changing the language does not translate existing UI labels, stored world
descriptions, opening text, quests or earlier memories. Compression can still
produce its English chronicle under the separate memory contract. Text-log
translation remains available via its existing button. Original entity names and
speaker identifiers are preserved so portraits, commands and game objects retain
their identity.

The saved Bable Fish choice also selects locally bundled session fonts: Alegreya
Sans for Latin/Cyrillic, Baloo Bhaijaan 2 for Arabic, M PLUS Rounded 1c for Japanese,
and Noto Sans SC, TC or KR for the corresponding scripts. Mixed-language prose
keeps its text direction without reversing interface controls. See the
[bundled font inventory and licenses](../frontend/public/assets/fonts/session/README.md).

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

Automated tests use mocked models and an isolated database. They verify language
propagation and persistence, not the multilingual quality of a particular model.

## Implementation and verification

- `backend/core/content_language.py`: accepted names, locale aliases and prose policy.
- `backend/api/routes/adventures/session_language.py`: owner-scoped persistence.
- `frontend/src/components/game/BableFishSelector.vue`: current session selector.
- `frontend/src/utils/sessionTypography.ts`: language/script font mapping.
- `tests/test_session_content_language.py`: scope, language propagation, copy and
  checkpoint regression coverage.

The language column and its migration are already part of main. Earlier branch
comparison counts, inherited lint errors and pre-merge status are historical
results rather than current installation requirements.
