# Adventure authoring validation and completion

The editor and the optional post-generation pass share the same validation, suggestion and application path.

## Review findings addressed

The original structural validator checked references, topology and gameplay but did not report missing structured personality or clothing data. The fix context omitted protagonist data, inventories, visual profiles and garment metadata. The fix allowlist and prompt accepted mostly scalar prose fields, so proposed structured repairs were discarded. Applying a patch removed its finding without checking whether structural gaps remained.

## Current coverage

| Data | Validation | Repair |
| --- | --- | --- |
| NPC description, goal, character and seven personality tendencies | Grouped character warning for absent or invalid values | Preserve established tendencies; fill missing choices using the canonical enum catalog |
| Protagonist and NPC visual identity | Missing/invalid appearance is reported | Add structured appearance without overwriting established facts; age and gender remain optional |
| Empty structured outfit | Review required, not an assumption of nudity | Use existing owned garments, or create a compact suitable outfit as canonical items |
| Wearable slots, layers and coverage | Missing/invalid garment metadata | Typed slot and garment data; no inferred combat bonuses |
| Inner layers | Review for an established adult when mature and detailed clothing are both enabled | Ordinary underwear items follow ownership, layer and coverage rules; same-proposal age guesses do not unlock inner layers |
| Scene description | Empty descriptions are deterministic findings; vagueness and coherence use full AI validation | Expand layout, light, atmosphere, existing landmarks and interaction affordances while retaining clues, exits and physical facts |

An outfit is not a requirement to fill every equipment slot. Animals, incorporeal beings and explicit story exceptions can carry an `outfit_exemption` reason. Unknown ages stay unknown. Mature and detailed-clothing preferences are author-owned; proposals cannot switch them on.

## Application behavior

- Typed proposals are visible under **Review field changes** before applying.
- Existing valid traits, appearance facts and occupied equipment slots are preserved.
- New garments are stored once as template objects, added to the owner's inventory and referenced by `visual_profile.worn`. Free protagonist equipment slots are populated where appropriate.
- Reapplying the same outfit does not duplicate its items. Existing garments owned by another character are rejected.
- The manifest snapshot is synchronized for character/outfit completions. Active session state is not edited.
- After applying a fix, deterministic validation runs again. Unresolved gaps remain visible and do not count as successfully repaired by the automatic pass.

The automatic pass retains its existing limit of 12 attempted findings. Extra findings remain open. Empty optional scripts, weapons, rings, demographic fields and other unrelated settings are not automatically populated. AI judgment still requires review: no word-count threshold can establish the quality of a scene description.
