# Portable agent runtime contract, version 1

Status: proposed shared feature contract, implemented here as authoring schemas,
opaque transport, validation and capability negotiation. It is not an official
upstream standard. Importing a blueprint does not enable background execution,
download RAG corpora or overwrite existing games.

## Upstream boundary

The namespace is `extensions.agent_runtime`; NPC seeds live in
`npcs[].metadata_json.agent_runtime`. Neither name identifies a person or fork.
The parent adventure format stays at `1.3`. Each of these two extension objects
requires the integer `schema_version: 1`; the NPC version is explicit so a copied
character remains interpretable without its parent manifest.

Upstream preserves valid namespaces without interpreting their version. Its
[format specification](https://github.com/jschm42/taleweaver/blob/47fc1292a78e2f995f2b0feb6bec3410e8cd6765/docs/specs/adventure_format.md)
and [Discussion 92](https://github.com/jschm42/taleweaver/discussions/92) are the
compatibility boundary, not a promise of agent behavior in the original engine.
The namespace normalizer is adapted from upstream's MIT-licensed
`backend/core/manifest_extensions.py` at that commit.

Upstream limits are 32 namespaces, keys matching
`^[a-z0-9][a-z0-9_.-]{0,63}$`, object values and a 256 KiB UTF-8 JSON budget.
The existing upstream implementation counts the serialized namespace **values**,
in insertion order; over-budget or malformed entries are dropped, while other
manifest content remains importable. This implementation matches that behavior.
An explicit empty `extensions` removes it; omission during a generated edit keeps
the existing authored block. Unknown nested fields, including JSON null, survive.

## Ownership and minimum fields

| Location | Contents | Owner after session creation |
| --- | --- | --- |
| `extensions.agent_runtime` | Adventure-wide defaults and feature requirements | Frozen session manifest snapshot |
| NPC core fields | `id`, `character`, `goal`, `start_scene_id`, `image_url` | Existing world/entity mechanisms |
| `metadata_json.personality_profile` | Authored categorical traits | Existing personality profile catalog |
| `metadata_json.agent_runtime` | NPC autonomy and initial situation/relationship/knowledge seeds | Session initialization adapter |
| `SessionState.entity_states.__chpm__` | Observations, source-bound beliefs, experience, agenda and mind snapshots | CHPM reducers and lifecycle code |
| `SessionState.living_world` | Clock cursor, events, decisions, revision and timeline | Living World |
| World Info / memory SQL rows | Canonical corpus entries, revisions, visibility and source evidence | Existing RAG and World Info services |
| Embedding indexes | Derived retrieval cache, never canonical memories | Existing memory index lifecycle |

Only `schema_version` is mandatory inside an extension. All capabilities default
to disabled. The minimal examples remain ordinary playable core adventures.

| Adventure field | Default / bounds | Meaning |
| --- | --- | --- |
| `required_features` | `[]`, max 32 | Exact versioned capability IDs needed by the runtime |
| `optional_features` | `[]`, max 32 | Capabilities that may be skipped, with diagnostics |
| `fallback` | `core` or `block` | Whether a host may offer ordinary core play without this runtime |
| `autonomy.enabled` | `false` | Request autonomous NPC scheduling |
| `autonomy.max_active_npcs` | 3, 1–20 | Requested per-cycle selection limit, clamped by host limits |
| `psychology.enabled` | `false` | Request observer-local psychological processing |
| `psychology.model` | `authored-categorical-v1` | Use authored labels; do not infer numerical trait scores |
| `psychology.observer_memory_limit` | 12, 0–24 | Bounded quotation window; does not erase canonical history |
| `rag.enabled` | `false` | Request retrieval from available canonical sources |
| `rag.top_k` | 8, 1–32 | Retrieval result limit after audience filtering |
| `rag.audience_policy` | `observer-scoped-v1` | Apply existing visibility before building NPC context |
| `rag.corpora` | `[]`, max 32 | Pinned authored corpus references, not live memory or vectors |
| `living_world.enabled` | `false` | Request world progression through the existing scheduler |
| `living_world.absence_mode` | `pause` or `catch_up` | Consume absence through the host clock exactly once |
| `living_world.max_catchup_minutes` | 360, 0–4320 | Upper bound on one catch-up run |
| `living_world.max_events` | 16, 0–128 | Per-run event budget |

| NPC extension field | Default | Meaning |
| --- | --- | --- |
| `schema_version` | required, 1 | Independent seed schema version |
| `autonomy` | `off` | `off`, `reactive` or `proactive`; cannot bypass adventure/host capability gates |
| `initial_state.situation` | empty, max 1000 characters | Authored initial psychological context, not a mutable mood value |
| `initial_state.relationships` | `[]`, max 32 | Authored `{target_id, description}` seeds; target must be another NPC or `PROTAGONIST` |
| `initial_state.knowledge_entry_ids` | `[]`, max 64 | IDs of initially known installed entries, still subject to source visibility |
| `visual_reference` | `image_url` | Refer to the canonical packed NPC image field |

`goal`, `character` and the categorical personality profile stay in their current
fields, avoiding a second source of truth. A descriptive relationship seed is
authored fiction, not a calibrated trust score. The current CHPM uses qualitative,
source-grounded experiences; this contract adds no Big Five, diagnostic or
numerical emotion claims. Changed relationships and experiences belong to the
session. Reserved mutable fields (`memories`, `relationships`, `session_state`,
`runtime_state`, `psychological_state`) at the extension root fail activation
validation; opaque import still retains them for review.

## Feature negotiation

| Capability ID | Meaning / dependency |
| --- | --- |
| `npc.autonomy.v1` | Per-NPC reactive/proactive initiative through host action validation |
| `psychology.authored.v1` | Observer-local psychology using authored categorical identity |
| `rag.observer.v1` | Visibility-filtered retrieval with source provenance |
| `living_world.v1` | Existing world scheduler and pause semantics |
| `living_world.catch_up.v1` | Catch-up; requires `living_world.v1` |
| `library.remote.v1` | Resolve pinned remote RAG resources; requires `rag.observer.v1` |

Every enabled configuration capability must be declared required or optional.
Lists must be unique and disjoint. A required child requires a required parent.
The presence of a declaration does not turn on its configuration section.
An unsupported optional feature and its dependents remain inactive. A required
corpus also requires required RAG support, and required remote support if remote.

`inspect_runtime(raw, supported=...)` returns `absent`, `invalid`,
`unsupported_version`, `missing_required` or `ready`, plus exact missing/ignored
IDs, unknown field paths and an active feature set. Booleans, strings and floats
are not valid schema versions. There is no automatic future-version downgrade.
`inspect_manifest` additionally checks NPC versions and relationship targets.
NPC-only data without the adventure namespace cannot activate a runtime.

Unknown fields are preserved in the source JSON and reported; execution adapters
must use `known_projection`, which excludes them. A newly added behavior that
must execute needs a versioned capability; it cannot rely on an ignored field.
Breaking shape/meaning changes increment the integer schema version. Additive
fields with safe defaults do not. Migrations must be explicit, pure and tested;
no implicit migration is registered in version 1.

The inspector defaults to **no supported capabilities**. This PR supplies a
contract and negotiation API, not a claim that every existing subsystem already
implements its portable activation adapter. Hosts advertise only adapters they
actually wire and test. Import/edit/export paths deliberately do not call engines.

## Initialization and save lifecycle

At a future activation integration, negotiate capabilities and validate both
scopes before mutating a session. Resolve required static resources first, then
initialize once in the host's existing transaction. Resolve knowledge IDs against
the installed corpus and validate visibility; author data cannot widen its ACL.
An unresolved required resource blocks activation; optional omissions are shown.

Use the existing manifest snapshot for a new game. Do not reread a changed live
template into an existing mind. Copy/restore uses current CHPM source rebinding,
World Info portability and Living World timeline forking; never replay seed data
over an existing save. A failed validation leaves the last valid session intact.
Deleting an NPC or changing its ID requires validating its seed references again;
this patch does not rewrite opaque third-party data during entity renames.

Map supported defaults to existing CHPM Settings and Living World Settings at
session creation. Preserve `ensure_compatible`: CHPM live control and Living World
private deliberation must not control the same NPC simultaneously. The scheduler
proposes work; the host resolves actions and keeps the authoritative game clock.
No alternative psychology state store or second simulation clock is introduced.

The [session-state fragment](agent_runtime/examples/session-state.fragment.json)
uses current validated CHPM and Living World schemas. It is illustrative save
content, not an importable adventure or a universal cross-engine save standard.
State versions (`__chpm__` currently 6, core projection 4, Living World 1) remain
owned by their existing implementations and are independent of extension v1.

## Modular remote libraries

The adventure catalog already introduced by PR 8 remains in
`backend/services/adventure_library/`: `models.py` owns index contracts,
`catalog.py` owns index/cache orchestration, `downloads.py` bounded transport and
`installer.py` conversion/import. The HTTP routes only coordinate these services.
Vue has a transport service, a loading/selection composable, a pure filtering
composable and dialog/card components. Browse, retry, refresh, cached offline
view and install/update can be maintained separately.

The adventure catalog index (`library.json`) and a RAG corpus are different
resource types. Do not interpret one as the other or teach CHPM about HTTP.
RAG references use a separate `CorpusLibrary.read(id, revision, max_bytes=...)`
port in `backend/services/runtime_resources.py`. `resolve_corpora` accepts an
installed adapter and injected remote adapters indexed by local `library_id`.
It verifies SHA-256 and the 8 MiB resource limit before returning canonical bytes.
Adapters own download limits, timeout, redirects, cache, credentials and revision
lookup. There is no bundled live remote RAG provider in this PR.

Each corpus reference has `id`, `source` (`installed` or `remote`), an exact
`revision`, lowercase 64-character `sha256`, and `required` (default false).
Only remote references have `library_id`. Endpoints, keys, local paths, embedding
provider/model and vector dimensions stay in local configuration. A hash pins
content, not publisher trust. Ingestion uses existing World Info validation and
visibility; retrieval never bypasses it. Vector caches rebuild when the existing
embedding signature changes.

Missing adapters, network failures and integrity mismatch are explicit optional
omissions or required failures. Resolution performs no database writes. Callers
pass only negotiated capabilities; imports never fetch a URL from manifest text.
The example corpus is intentionally empty, and its hash matches its exact bytes.

## Compatibility with original TaleWeaver

Normal ADV/ADZ export retains valid extensions and NPC seed JSON, including
unknown fields and unknown versions. Original TaleWeaver ignores their behavior.
Only core `image_url` paths are packed; strings buried in `extensions` are opaque
and do not acquire asset packing or extraction semantics.

The PR 8 converters now accept and preserve the namespace. Preparing an original
engine copy reports behavioral loss and requires the existing acknowledgment.
`fallback: block`, invalid or unknown `agent_runtime` versions block that copy.
If publication filtering would alter opaque extension data, preparation fails
for manual review instead of silently exporting a broken custom contract.
That preparation action still does not publish an adventure online.

## Files and verification

- [Adventure JSON Schema](agent_runtime/v1.schema.json)
- [NPC JSON Schema](agent_runtime/npc-v1.schema.json)
- [Minimal adventure](agent_runtime/examples/minimal.adv)
- [All configuration sections](agent_runtime/examples/full.adv)
- [Unsupported future-version transport example](agent_runtime/examples/unknown-version.adv)

Regenerate schemas with `poetry run python -m scripts.export_agent_runtime_schema`.
Tests cover strict versions, feature dependencies, unknown/null preservation,
namespace limits, actual ADV/ADZ import/edit/export, public-copy fallback,
adapter injection, pinned resources, catalog APIs and browser filter behavior.
Existing session copy/restore tests exercise their current state owners.
