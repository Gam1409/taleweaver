# Storage identifiers and multilingual names

New adventures, saved sessions and their copies use UUIDs rather than IDs built
from their titles. The identifiers fit the existing 36-character database columns.
Titles, NPC names and descriptions remain separate display/content fields and
keep their original language. Explicit blueprint IDs and existing save IDs are
preserved; this change does not rename folders or migrate running games.

Older versions generated IDs such as `одинокий-путник-ab12cd34`. These are still
supported by the shared path validators. Unicode letters and digits are allowed;
path separators, traversal, unsafe controls and symlink escapes remain rejected.
New code should allocate IDs, not transliterate display names into paths.

## Paths checked

| Flow | Behavior |
| --- | --- |
| Create/start/copy sessions and adventures | New UUIDs; titles retained in records and snapshots |
| Session `.ads` export/import | Legacy Unicode IDs and UUIDs download through the API, including assets; imports allocate a new UUID |
| Blueprint `.adz` export | Unicode filenames use RFC 6266/5987 download headers instead of raw Unicode HTTP header bytes |
| Cover and editor image uploads | Legacy Unicode IDs pass the shared validator; uploaded files receive unique technical names |
| NPC portrait jobs | First portraits and replacements support legacy saves and remain scoped to the owning session |
| Imported image thumbnails and reused visuals | Unicode basenames no longer fail redundant ASCII-only checks |
| World generation / source-adventure reuse | Existing multilingual template IDs use the same path validation policy |
| Speech files | Clips stay under the concrete session's `tts` directory, including legacy Unicode sessions |
| Style/tone catalog tiles | New entries allocate one UUID, reused for generation, upload, save and rename; missing legacy IDs get a deterministic fallback |

Known ASCII restrictions on symbolic scene/object/script identifiers and file
extensions are separate format rules, not restrictions on display language.
Generated media filenames remain technical identifiers. Provider URLs, ComfyUI
node names and installed model filenames are not rewritten by the storage-ID
change. Existing explicit catalog IDs are preserved; previously saved duplicate
IDs cannot be automatically disambiguated without changing references.

## Verification

The follow-up ran 231 backend regression cases, including export/import APIs,
ownership, traversal rejection, session snapshots, cloning, media, ComfyUI, TTS
and world manifests. Fixtures include Russian, Japanese, Arabic and Spanish
titles and a data directory named `Данные игры`. Three frontend service tests
cover separate IDs for localized/repeated labels and stable IDs across generation,
upload, rename and reload. External LLM/image/audio providers are mocked; this is
not a live GPU or Windows execution test.

The production frontend build and targeted ESLint checks pass. TypeScript retains
the same 129 normalized baseline diagnostics. Fifteen changed/new Python files
pass full Ruff checks and formatting. Four older modules retain 56 existing Ruff
diagnostics (58 before these changes), with no new diagnostics; their unrelated
complexity and formatting are outside this storage fix.

After updating the branch, restart the backend before retrying a failed export.
An existing save does not need to be renamed or restarted.
