# Turn evidence and player item checks

In a Visual Novel session, **Session settings → NPC Personality** offers a
strict check for player actions involving known items. It starts disabled,
including in existing saves. Enable it to catch actions such as handing over a
coat the player does not hold or removing a garment the character is known
not to be wearing. The rejection shows the reason and the passage from the
player's input. The player can dismiss the message and submit a revised action.

The check runs before the story input is saved. When a known item name appears,
the configured Small model can receive one request to identify performed actions.
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

LangExtract aligns a candidate with an exact occurrence inside its cited passage.
The host resolves an item only when the quoted name identifies one accessible
item. Inflected names, synonyms and pronouns may remain unresolved. A matching
quote establishes what appeared in the text. Whether the right person acted,
which object they meant and whether an event was completed still depend on
interpretation. Posture, clothing, custody and emotional cues are covered by
this review. A review is limited to 12,000 characters per source.
