# World blueprints and open-ended author briefs

A blueprint gives the AI the information it needs to create a coherent starting world. It does not need to prescribe an ending, a successful romance or the player's future choices.

Both adventure creation screens keep the ordinary concept field and add an optional **World blueprint** panel:

| Field | What to establish |
| --- | --- |
| Setting & canon | Genre, era, geography, technology or magic; which interpretation of a setting to use. |
| History before play | Events that already happened and the consequences that still matter. |
| Starting situation | The opening location, present people and events already in progress. |
| Important people | Identities, values, individual motives and existing relationships. |
| World constraints | Facts and limits that the generated world should respect. |
| Unresolved tensions | Conflicts, mysteries and opportunities whose outcomes remain open. |

For example, describe a city where two states maintain a fragile treaty, the incident that damaged trust, the people arriving for negotiations and the interests each wants to protect. Let play determine whether the talks succeed.

Leave the panel empty to keep the previous free-form generation flow. The detailed fields share a 12,000-character budget, separate from the ordinary concept field's 20,000-character limit.

## Reference pages and excerpts

Add up to three public HTML/plain-text URLs. An optional note explains which facts matter and which parts of a setting should be disregarded. A pasted excerpt, up to 3,000 characters, can replace downloading a page; a source may consist of that excerpt alone.

When generation begins, TaleWeaver reads bounded excerpts and saves them with the adventure. A resumed generation reuses its snapshot instead of downloading a potentially changed page. Changing a reference invalidates its cached snapshot. Each page gets a 12-second overall deadline, at most three redirects and a 512 KB read limit; at most 3,000 readable characters per source enter generation context. The reader does not crawl linked pages, execute JavaScript, log in or read a whole wiki. Use a specific article, or paste the relevant section when a large article's opening is insufficient. An unreadable source produces an explicit generation error; paste an excerpt or correct the source before retrying.

A saved brief can be edited under **Adventure editor → World**. After fixing a URL or supplying a pasted excerpt, save the blueprint and resume a failed generation. Changed reference inputs invalidate their snapshot; changed generation context invalidates incompatible stage checkpoints. Existing sessions keep their saved world. Editing is blocked while generation is active.

The reader allows public HTTP(S) pages on ports 80/443. It rejects credentials, local/private/metadata addresses and unsupported protocols. DNS addresses are checked and the TCP connection is pinned to a checked public IP, while TLS still validates the original hostname. Redirect destinations receive the same checks. Enabling private model servers does not enable private reference fetching. No provider API keys, login cookies or browser credentials are sent to reference pages.

Source excerpts are untrusted factual material. They do not override the author's premise, game rules or character decisions. They are included in adventure exports, so review pasted text and URLs before sharing a world.

The brief and excerpts are used for world creation and its saved stages. They are not automatically appended to every RP turn or indexed as memories of events that an NPC witnessed. Gameplay receives the resulting world's existing plot, rules, people, places and session memory through the normal pipeline.

## Optional precise entity tags

Authors who want more control can also place structured tags in the concept field. The parser and Markdown grammar are adapted from [jschm42/taleweaver at 012599eff](https://github.com/jschm42/taleweaver/tree/012599effc53f96c1e16191fcf2223cc39330b0f), under the project's MIT license. Field definitions use this fork's current schemas, including character age, gender, personality profiles and clothing.

```text
A mystery in an observatory after the old alliance collapsed.

[Scene: OBSERVATORY] The rooftop observatory
description: ~A quiet laboratory above the harbour.

[NPC: MIRA] Mira
in: OBSERVATORY
age: 28
gender: female
goal: Protect her research and decide whom she can trust.
character: Independent, observant, dry humour; values evidence.

[Item: NOTEBOOK] Mira's notebook
in: OBSERVATORY
description: ?
```

- A normal `field: value` is fixed and reapplied during generation.
- `field: ~suggestion` is guidance; the AI may develop it.
- `field: ?` leaves the field open.
- Free prose describes design intent.
- Structured objects/lists such as `clothing`, `visual_profile` or `personality_profile` use JSON. Reference lists such as `inventory` also accept comma-separated IDs.
- Use explicit ASCII IDs for references. An NPC's `in` field points to a declared scene; an inventory item must exist and can have only one owner.
- `[Exit: A -> B]` specifies a directed route; `[Exit: A <-> B]` declares a bidirectional route.
- Markdown headings such as `## NPC: MIRA — Mira` are supported. Multi-line values use `field: |` and indentation or fenced blocks.

**Check blueprint** reports syntax, field, reference and configuration issues with line numbers. It makes no model call. The server repeats preflight before creating records. Fixed fields enter staged planning and detail validation before checkpoints are accepted. An omitted declared entity or an ownership conflict is an explicit validation failure, rather than a silently dropped requirement.

Chapter, quest, award, ability and script blocks remain subject to the selected game mode and generation switches. VN keeps its open-ended policy: use its world brief, personal goals and unresolved tensions rather than mechanical completion gates. Existing prose-only `[Sequence]` outlines still serve as possible VN themes, as before. This port does not add dialogue trees or predetermined dialogue outcomes.

## Storage and compatibility

The brief, source snapshot and narrator defaults use additive fields in existing manifest JSON. Session overrides remain in session JSON. No database columns or persisted schema version changes are required. Existing adventures without these fields keep their previous behavior. Imports, exports and session snapshots retain the author information; generated content cannot replace it.

Reference extraction is bounded and a source can be partial or outdated. It does not establish complete canon knowledge or prove that a model will honor every narrative detail. Live generation quality still depends on the selected model.
