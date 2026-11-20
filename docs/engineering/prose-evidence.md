# Turn evidence and player item checks

In a Visual Novel session, **Session settings → NPC Personality** offers a
strict check for player actions involving known items. It starts disabled,
including in existing saves. Enable it to catch actions such as handing over a
coat the player does not hold or removing a garment the character is known
not to be wearing. The rejection shows the reason and the passage from the
player's input. The player can dismiss the message and submit a revised action.

The check runs before the story input is saved. When a known item name appears,
the Small model reads the message to identify performed actions.
The host checks earlier actions in that message in order on a temporary view of
possessions and clothing. Only the normal gameplay owners can update the world.
Requests, memories, unknown item names, ambiguous references and incomplete
wardrobe records can leave a contradiction undetected. A provider failure during
the check is reported separately so the player can retry.

With gameplay Debug enabled, **State → Turn evidence → Review latest turn**
can inspect the latest published exchange. Each message is reviewed separately
using the configured Small model. The diagnostic shows the source, quoted
passage, supported event and resolved IDs. The last unambiguous mention is
marked within its own source. The original pre-turn snapshot supplies the
visible identities. A missing snapshot leaves item references unresolved.
Play can continue during inspection. Each result refers to the captured message
revision and remains available if the other source fails. Reviewing a turn
leaves the story and saved state untouched.

In Intelligence settings, **Pass 1: Mechanics & Rule Engine → Prose extraction passes**
sets the number of independent Small-model reads per message (1, 2 or 3, default 1).
This shared setting also applies to the optional VN player item check. A Debug review of
both messages uses up to 2, 4 or 6 requests respectively. Extractions are aligned
to their original text before merging. New findings are added in source order, including
distinct subjects or kinds of action in the same passage. Within a single response,
repeated findings for the same action, participants, item and exact source occurrence
count once. The same action at a later position remains a separate event.
Across passes, overlapping duplicates count once and an earlier finding takes
precedence over a conflicting later one.
Conflicts prevent an item-based rejection.
If a later request fails, Debug marks the completed results as partial. The player
item check reports an unavailable check so the player can retry.

LangExtract aligns a candidate with an exact occurrence inside its cited passage.
The host resolves an item only when the quoted name identifies one accessible
item. Inflected names, synonyms and pronouns may remain unresolved. A matching
quote establishes what appeared in the text. Whether the right person acted,
which object they meant and whether an event was completed still depend on
interpretation. Posture, clothing, custody and emotional cues are covered by
this review. A review is limited to 12,000 characters per source.
