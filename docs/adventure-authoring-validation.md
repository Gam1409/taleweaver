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

- **AI-Fix is available on structural and AI findings.** Missing character details and clothing are structural findings, so they can be sent directly for suggestions without running an AI validation pass first.
- Typed proposals are visible under **Review field changes** before applying.
- Existing valid traits, appearance facts and occupied equipment slots are preserved.
- New garments are stored once as template objects, added to the owner's inventory and referenced by `visual_profile.worn`. Free protagonist equipment slots are populated where appropriate.
- Reapplying the same outfit does not duplicate its items. Existing garments owned by another character are rejected.
- The manifest snapshot is synchronized for character/outfit completions. Active session state is not edited.
- After applying a fix, deterministic validation runs again. Unresolved gaps remain visible and do not count as successfully repaired by the automatic pass.

Opening a finding again can reuse its suggestions. **Retry explicitly regenerates them** using the configured model, including after a rejected clothing proposal; it does not keep returning the same cached result. Proposals that contain no supported field changes are reported as unusable rather than offered as applicable fixes. A no-op application clears that finding's cached suggestions.

The automatic pass retains its existing limit of 12 attempted findings. Extra findings remain open. Empty optional scripts, weapons, rings, demographic fields and other unrelated settings are not automatically populated. AI judgment still requires review: no word-count threshold can establish the quality of a scene description.

## Workflow verification

`tests/test_ai_fix_workflow.py` exercises the real authenticated suggestion/apply/assets routes with local model replies. It checks NPC and protagonist outfits, seven actual owned garments including a bra and briefs, worn layers, manifest synchronization, cache reuse, explicit regeneration, unusable proposals and repeated application without duplicates.

The browser fixture uses real editor components, HTTP endpoints and isolated in-memory SQL. Only the model is substituted. With development dependencies and test environment configured, run:

```sh
poetry run uvicorn tests.browser_ai_fix:app --host 127.0.0.1 --port 8019
# In another terminal, from frontend/:
BACKEND_PORT=8019 npm run dev -- --host 127.0.0.1 --port 5204 --strictPort
# From frontend/, with Playwright and Chromium installed:
FRONTEND_URL=http://127.0.0.1:5204 node tests/browser/aiFixSmoke.mjs
```

The fixture intentionally fails the first model request and then returns one invalid garment layer. The smoke check verifies visible retry, actual regeneration past the cached invalid proposal, review and confirmation, saved garments and persisted validation after reload. The server is test-only, binds to loopback, and uses no production adventure database or remote LLM. These checks verify the host/UI workflow; they do not establish a live model's ability to propose a complete, suitable outfit every time.
