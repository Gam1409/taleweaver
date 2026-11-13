# Session World Info

Open **Session → World Info** to add reference knowledge to the current playthrough.
Each session owns its sources, reviewed entries and recall index. An adventure
template never receives these uploads. Two sessions from the same adventure can
have different reference knowledge.

## Import and review

1. Choose a UTF-8 `.md` or `.json` file and select **Upload & analyse**.
2. The server stores an immutable source revision, then explicitly starts analysis
   with the configured Generator model. Sources needing more than 16 batches wait
   for **Start analysis** after showing their workload. Processing uses the session
   content language, falling back to the profile language; original quotations are retained.
3. Follow saved batch progress, fact and entry counts, UTF-8 byte sizes and character
   counts in **Files & processing**. Closing the window stops polling and leaves
   authorized background work running. Cancel retains completed batches; resume
   continues the same revision from its saved cursor.
4. Open **Review** to browse the catalog. Select a record to open its separate
   read view with statements, metadata and exact source evidence. Choose **Edit**
   to correct text, remove facts, adjust tags, connect related records and choose
   the audience. A record must retain at least one fact. A correction keeps the
   original quotation and is marked as an author edit.
5. Select entries and publish them, or preview a filtered collection and confirm its
   publication in one action. Collection publication requires stopped or completed
   processing; individually selected ready entries can be accepted while other
   batches continue. Extraction alone never makes a draft available
   to recall. **Active entries** shows accepted knowledge and allows later changes,
   unpublication or deletion.

**New entry** accepts written or pasted text and an optional source title. Analysis
uses the same configured Generator model, source budgets, progress tracking and
evidence checks as a file import. The exact UTF-8 text is saved as a new source in
this session; file and written sources share the displayed source quota. The model
may propose several concise records. They remain drafts until reviewed and published.
Large text sources wait for workload confirmation before analysis starts.

Unsubmitted text stays available while switching World Info tabs within the open
window. Closing asks before discarding it; switching sessions clears it. Failed
submissions retain the text. **Files & processing** places the file, destination,
optional title and upload action together above the source workspace.

JSON objects and arrays are parsed locally, then their scalar passages are analysed.
Duplicate keys, invalid numbers, excessive nesting and oversized files are rejected.
Markdown, HTML and links are displayed as plain source text. Importing a reference
does not fetch its links, execute instructions or change canonical game objects.

The model proposes facts, concise record groups, tags and related-record links.
The host verifies schemas, size budgets, source quotations, exact spans and session
ownership. These checks establish provenance and structure; the review step remains
necessary to assess interpretation and factual quality.

## Find and organize a large collection

The catalog supports **up to 10,000 compact records** with bounded server-side pages.
Entry count, fact count and serialized storage have independent ceilings; the
first reached limit stops further additions. Evidence-rich or longer entries can
fill the 32 MiB storage budget before reaching 10,000 records. Searchable UTF-8
text sizes do not measure that quota: source evidence, original proposals and
entry metadata also count. Search
matches all entered terms; combine a source revision, group, tag and record kind.
Sort by title, source or update order. Group and tag navigation shows SQL aggregate
counts rather than downloading all records into the browser.

The main window reserves its width for group navigation, search and record
summaries. Groups and tags stay in the left sidebar even in small collections;
search, kind, source-version and sort controls are visible above the results.
On narrow screens, **Groups & tags** opens the navigation panel and **Back to
entries** returns to the results. **Organize all matching entries** opens bulk
controls without hiding the regular filters. Reading and editing use a separate dialog, with only one dialog active
at a time. **Back** restores the catalog's filters, page and scroll, then focuses
the original record when it is still visible, or another available catalog control.
Closing an edited record asks before discarding unsaved changes. The same flow
works on narrow screens without squeezing an editor beside the catalog.

The extraction model proposes a primary named group and overlapping tags from the
source context in its existing response. A group organizes records; it does not
establish truth, visibility or priority. Rename/reassign groups and adjust tags for
one entry or an entire filtered collection. Bulk actions first show the exact count
and a bounded sample. Confirmation is bound to that selection's versions; concurrent
changes require a fresh preview. An invalid edit rejects the complete action.
Tag fields preserve each complete label, including spaces and a leading `#`;
adding or removing one tag must not rewrite the other saved labels. The same
identities apply to filtered bulk tag actions.

In **Review**, **Select this page** checks the currently displayed records, up to
50, with an indeterminate checkbox for a partial selection. **Publish selected**
shows its selected count and requires one source version. **Clear selection**
does not change saved records. Page and filter changes reset the page selection.
To publish across every page, select one source version and choose **Publish all
matching**. The count/sample preview and separate confirmation cover the entire
filtered result; the browser does not fetch thousands of selected IDs. Stale
versions and changed selections still require a new preview.

Record facts, original quotations and relationship controls are visible without
expanding accordions. The footer's **More actions** menu contains infrequent record
actions; reading evidence and selecting records do not depend on that menu.

Original source previews use bounded character pages. Large uploads show their
known batch count before analysis starts, with an explicit start action when more
than 16 batches are needed. A book can require many model requests and hours of
processing. Record capacity is a ceiling, not a promise that every possible fact in
a book will be extracted.

## Replacement and retention

Uploading a replacement creates another immutable revision. Accepted knowledge
from the previous version remains active during processing and review. Publishing
the new selection atomically archives the previous accepted version; unselected
new drafts remain drafts. Returning to an older revision activates only the entries
explicitly selected again. No source evidence is rebound to a different file.

World Info belongs to session editing rather than the gameplay timeline. Undo,
checkpoints and narration rewrites retain uploaded sources and author corrections.
Deleting a source removes its entries and incoming reference links, without deleting
chat messages or NPC memories. Concurrent edits use version checks; a stale update
is rejected and the browser retains the unsaved draft.

Session copies and `.ads` exports include World Info. Large collections use
checksummed archive parts under the existing per-entry and total ZIP safety limits;
small exports retain the inline representation. Copies/imports assign new
source, revision, entry and fact identities and remap links. Processing does not
restart automatically in the destination. Adventure `.adv` templates are unchanged.
Export reads session entities, conversation, summaries and World Info in one SQL
snapshot. Import inserts parent rows before their children inside the caller's
transaction, including when SQLite foreign-key enforcement is enabled.

## Audience and recall

- **Narrator only** is the extraction default.
- **Common knowledge** can also be used by the existing shared narrative context.
- **Selected characters** records an explicit scope for named session NPCs.

Selected recipients currently annotate references supplied to the narrator.
There is no production actor-recall consumer yet: these records do not enter
the selected NPCs' autonomous decision or NPC Personality memory requests.
Actor-scoped retrieval is tracked in [#28](https://github.com/Gam1409/taleweaver/issues/28).

Record kinds separately distinguish background lore, world facts, reported claims,
recollections/character knowledge, rumors, news and authored events. The model receives
explicit epistemic labels: a rumor is unverified, news is an attributed report rather
than automatically current truth, and a recollection remains subjective. Imported
event descriptions do not become committed gameplay events.

Support and contradiction links remain author-provided labels. A bounded link
summary can reach the model, but it does not expose linked record contents, prove
a statement or grant another character knowledge.

Retrieved records are optional candidates. The model is instructed to omit irrelevant,
redundant or superseded material, preserve uncertainty and conflicts, and avoid treating
retrieval order or upload dates as proof. Host ranking already filters candidates
without lexical, semantic or entity relevance. These contracts and prompt-boundary
tests do not establish perfect live-model interpretation.

Foreground reference retrieval keeps at most 16 recent, 32 lexical and 32 semantic
candidates before deduplication. Lexical selection reserves space per query term
before filling the shared budget, so broad context terms do not consume every
lexical slot ahead of an older, more specific match.

Known-by metadata constrains narrative references. Publishing does not create an
NPC observation, memory episode or belief; NPC Personality keeps its existing
evidence rules. Imported references never enter the mechanics request or grant
items, access, actions or state transitions.

### Living World, Concordia and character memory

World Info currently supplies narrative references; it does not feed autonomous
Living World decisions. Living World already supplies an actor's own recent
committed events to its decision context. The optional Concordia adapter invokes
the same decision callback and has no separate retrieval store. NPC Personality
already retrieves observed episodes and beliefs through its character memory
mechanisms. These are distinct from author-provided reference knowledge.

A future autonomous reference lookup ([#28](https://github.com/Gam1409/taleweaver/issues/28))
should reuse World Info with an actor scope:
common knowledge or explicitly resolved recipients, filtered before candidate
limits. It must keep reference material separate from witnessed memories and
preserve current-state authority. Passing the narrator's entire recall block to
an actor would be unsafe: other historical layers do not establish actor access.

Committed Living World events are not automatically public. A future event-to-RAG
projection needs an explicit audience and observation policy, stable event
identities and timeline provenance before indexing. Private goals, beliefs and
plans must remain private. No such projection is added by this feature.

A possible sliding recall window ([#27](https://github.com/Gam1409/taleweaver/issues/27))
should bound the active prompt, not delete older knowledge: retain recent events,
retrieve relevant older evidence, and expire
derived candidates when state or source versions change. This is a design option,
not an additional retrieval mode implemented here.

A recipient removed by a timeline change can remain attached to a retained entry.
Copy/export marks unavailable recipients as unresolved. They stay dormant in the
destination even if an NPC later has the same identifier. An explicit reassignment
to a current session character is required; ordinary text saves do not reactivate
them. The narrator can still inspect the scoped reference.

Publication saves canonical SQL knowledge independently of vector maintenance.
If memory recall is enabled, a paused or unavailable embedding service retains
lexical recall. If recall is globally disabled, saved entries are not retrieved;
enable it in **Administration → Memory & recall**, or ask an administrator.
**Rebuild this session's index** affects
only the current session and explicitly resumes its index maintenance.

## Processing and limits

Processing runs in bounded background units behind foreground game requests.
Each batch uses one structured extraction and at most one validation correction;
provider/router retries retain their configured behavior. Request counters represent
logical extraction requests, including corrections, rather than billing totals.
Each revision has a cumulative budget of four logical requests per parsed batch.
Cancel, resume and service restart retain the counter. Reaching the budget stops
further dispatch while preserving completed batches and reviewed entries; the
last allowed valid response can still be saved. Uploading an unchanged file does
not reset its budget. Further analysis requires a corrected source revision.
Unstarted legacy sources determine their batch count and budget when started.
Provider/router retries are outside this logical counter, so this is not a
currency or exact HTTP-request spending limit.
Only malformed completed output qualifies for a correction request. Queue pressure,
uncertain inference, transport failures and timeouts retain their operational
meaning instead of triggering another extraction. Invalid model configuration
becomes a visible, resumable processing failure rather than stranding queued work.
Cancellation revokes the result's write capability; an already dispatched remote
request may still finish at the provider.

Limits are shared by upload, processing, editing and import:

| Resource | Limit |
| --- | --- |
| Source file | 8 MiB UTF-8 and 4,194,304 characters |
| Sources per session | 32 |
| Immutable revisions per source | 8 |
| Stored source bytes per session | 16 MiB |
| Entries / facts per session | 10,000 / 80,000 |
| Escaped canonical entry data per session | 32 MiB |
| Searchable text per entry | 2,400 characters |
| Facts per entry / fact text | 8 / 500 characters |
| Primary group name | 80 characters |
| Tags per entry / tag text | 12 / 48 characters |
| Related entries / recipients | 12 / 32 |

Quota failures preserve existing accepted records and completed work. Free space
before explicitly retrying. World Info status and API errors use fixed host-authored
messages. Transient router retry warnings retain provider, role and exception class
without copying raw exception text. Existing optional model telemetry retains its
application-wide configuration; raw debugging can include model inputs and outputs.

## Implementation boundaries

`world_info_sources`, `world_info_revisions` and `world_info_entries` are canonical
session-owned SQL data. A revision is also the durable processing job: its cursor,
run token, control version and expiring lease fence every result write. SQLite save
retries reuse the validated response and deterministic identities without repeating
the model request. No database transaction spans model inference.
Exhausted SQLite contention while claiming work or looking up its next lease
schedules a cancellable wakeup. This deferral does not wrap or replay model work.

`backend/engine/world_info/` owns parsing, extraction, persistence, review and
projection. `/api/adventures/{game_id}/world-info` exposes owner-only operations.
Publication joins the existing session mutation lease and invalidates the current
session's derived recall epoch in the same transaction. Draft upload and processing
controls remain usable during gameplay. Index retrieval reloads current SQL content
and scope after embedding awaits, rejecting stale or deleted references.
