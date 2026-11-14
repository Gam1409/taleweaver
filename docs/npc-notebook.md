# Private NPC notebooks

NPC Personality can give each NPC one private, freely organized JSON notebook.
It is disabled by default. The NPC chooses what to read, write, edit or delete
within the existing optional agent tool rounds. There is no background reflection
loop or separate notebook inference request.

## Enable notebooks

In a Visual Novel session, open **Session Memory & Settings → NPC Personality**,
choose **Enabled**, and check **Private NPC notebooks**. Checking the option
selects at least one **Agent tool round per active NPC**. Increase the request
budget if the displayed minimum exceeds the saved limit, then save.

Adventure editors can choose the same option under **NPC Personality → Request
limits & agent lookups**. Save the adventure to apply those defaults to new
sessions. Existing sessions keep their own settings.

Old saves load with `notebook_enabled=false`; `agent_steps=0` remains the default.
Enabling notebooks preserves an existing choice of two rounds. Disabling notebooks
keeps the selected agent rounds; choose **Off** for those rounds to stop their
additional requests. Standard and Observe modes do not run notebook tools.

The existing live request reserve is `active NPCs × (1 + agent_steps) + 5`.
For three active NPCs, that means 8 requests with rounds off, 11 with one round,
or 14 with two rounds. Each invoked round costs one model request and permits up
to two local tool operations. The model can stop early. The ordinary narrator
request remains separate. Enabling notebooks does not silently raise any budget.

## Contents and authority

The notebook has no required sections or psychological schema. Any JSON value is
allowed within the technical limits below. An NPC may keep thoughts, feelings,
quotations, guesses, plans or decisions without citing transcript evidence.
These notes may be mistaken, incomplete or contradictory.

Notes remain the NPC's own subjective material. They do not establish objective
world facts, complete actions, change possessions, control the player, or reveal
another NPC's mind. Writing a wish or decision cannot change authored identity,
create an official belief, or bypass existing action and evidence checks.
Selected notebook reads reach the decision model as private subjective context;
they are not added to the world-evidence citation catalogue or automatically
copied into the narrator's input.

Notebook strings are inert data. Text resembling code, instructions, URLs or file
paths is never evaluated or opened by these tools. The host supplies the session
and NPC scope; the model cannot choose a different notebook owner.

## Local tools

| Tool | Behavior |
| --- | --- |
| `notebook_info` | Returns the current technical counter, used bytes and remaining capacity. |
| `notebook_read` | Reads a bounded page of a JSON value selected by its pointer. |
| `notebook_write` | Replaces the root, sets an object member or array slot, or appends to an array. |
| `notebook_edit` | Atomically applies `add`, `replace`, `remove` and `test` operations. A failed operation keeps the preceding staged document intact. |
| `notebook_delete` | Removes a value. Deleting the root clears the notebook to `{}`. |

Paths use JSON Pointer: `""` selects the root, `/plans/0` selects an array element,
`~1` represents `/` in a key, and `~0` represents `~`. Missing parent containers
are not created automatically. Array indices are nonnegative canonical integers;
`-` appends when writing or adding. A JSON `null` value is distinct from a missing
path. An edit's `add` inserts an array element; `write` sets an existing slot.

Read offsets count characters in the selected value's canonical JSON, including
its quotes and escapes. Results contain `json_fragment`, `next_offset` and
`complete`; a partial fragment is not a complete JSON document. The default read
budget is 1,400 serialized response characters, including escaped content and
metadata. Exposed tool requests accept budgets from 256 to 1,400 characters.
The full notebook is never automatically inserted into a model request.
With notebooks enabled, tool audits retain hashed arguments and result metadata,
so quoting a private note in a legacy memory-search argument does not copy it into
the audit. Notebook contents are never evidence pins.

The model sees its staged changes in later operations and subsequent rounds of
the same turn. Mutation requests include the expected technical counter; a stale
counter rejects the operation. A successful change advances that counter.
This is an ordering and conflict check, not a stored notebook version.

## Capacity and validation

Each current notebook is limited to **16,000,000 canonical UTF-8 JSON bytes**.
That includes keys, punctuation, quotes and escapes. Non-ASCII characters count
their UTF-8 bytes. Object keys are sorted and insignificant transport whitespace
is removed; whitespace inside strings is preserved.

A session can hold at most 32 current notebooks, including dormant notebooks,
for a maximum of 512,000,000 canonical bytes. Existing notes are never discarded
automatically to create another notebook. Repeatedly generating different NPCs
and undoing their introduction can eventually reach this limit; further notebook
creation then fails while existing notes remain saved.

Technical safeguards allow at most 64 nested containers and 250,000 JSON nodes,
counting object keys as well as values and containers. A full-size scalar string
can still use the entire byte allowance. Non-finite numbers, duplicate object
keys, invalid Unicode and values outside JSON types are rejected. Raw structure
is checked before parsing, and serialization stays within the byte budget.

Exposed writes carry at most 8,192 JSON-text characters; pointers have the same
character limit. One edit request contains at most 16 operations. Existing model
output and request-input budgets also apply. Large notebooks grow through bounded
operations or an explicit session transfer; the capacity is not a promise that
one model response can produce 16 MB.

A failed mutation leaves the preceding staged document unchanged. A failed or
cancelled turn does not publish its pending edits. Accepted edits replace the
current notebook in the same transaction as the successfully reviewed reply.
The host checks the current row's counter before replacing it.

## Latest notes survive Undo and Chronicles

There is one mutable current document per NPC in a session. There are no stored
notebook versions, edit history, automatic backups or notebook payloads inside
turn snapshots and Chronicles. Undo, regeneration, historical message edits and
Chronicles restore keep the latest notebook, even when other session state moves
back. Changing NPC Personality mode or selection also keeps it. An NPC may
therefore retain a fallible note about an event removed from the story.

If Undo removes a generated NPC, its latest notebook remains saved but dormant.
The host grants no notebook tool access until that same canonical NPC exists
again in the session. Retaining notes does not create an NPC or grant capabilities.

Session copy, export and import transfer only each NPC's current document.
Portable dormant entries carry a host-derived `dormant=true` marker; import does
not create the missing NPC. Once the same NPC returns, it can use its latest
notebook. A copied or imported session owns its own current documents.
Session archives also enforce their shared transfer limits: 2 GiB unpacked in
total, 50 MiB per member and 1,000 entries. Only current notebooks are transferred.

This notebook persistence is separate from source-checked psychological history,
which continues to follow its existing source-retraction and snapshot rules.
Neither counter values nor integrity hashes provide access to an older notebook.

## Validation scope

Local regressions cover exact byte limits, Unicode, invalid JSON, bounded reads,
atomic edits, staged visibility, scope and counter checks, cancellation and
review failures, and session lifecycle handling. These deterministic checks do
not establish improved live-model recall or psychological quality.
