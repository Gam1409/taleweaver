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

An adventure's `origin_id` is a separate portable story identity. Catalog
comparison canonicalizes UUID spelling but preserves the case and spelling of
legacy non-UUID keys. Existing template/session storage IDs are not rewritten.
See [catalog installation and identity](adventure-catalog.md#installing-an-adventure)
for the incoming catalog bounds and update behavior.

## Verification

`tests/test_language_independent_ids.py` and
`tests/test_unicode_storage_routes.py` cover generated identifiers, legacy paths,
ownership and traversal boundaries. Catalog identity tests additionally exercise
legacy keys, Unicode and differently cased UUID spellings. Frontend catalog tests
cover distinct IDs for repeated/localized labels and stable IDs across generation,
upload, rename and reload.

Fixtures include several scripts and a Unicode data-directory name. External
LLM/image/audio providers are mocked; these checks do not establish live GPU quality
or execution on every operating system. Current lint, types, tests and builds are
defined in [CI](../.github/workflows/ci.yml), rather than the old branch's diagnostic
counts.

Restart the backend after updating before retrying a failed export. Existing
saves do not need to be renamed or restarted.
