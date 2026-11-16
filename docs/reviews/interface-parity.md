# Interface parity review

This review compares the interface changes with the current `origin/main` and
checks the existing data owners, actions and configuration gates. No main-only
changes were identified at review time. Presentation changes do not introduce a
new adventure schema, session state store or model-generation pipeline.

## Authoring

| Area | Preserved behavior | Evidence |
| --- | --- | --- |
| Creation | Simple and Advanced modes, title/concept retention, generation language, selected visual style and rule mode | `authoringChecks.mjs` checks mode changes and the outgoing creation payload. |
| Generation gates | Missing LLM configuration blocks generation; missing image configuration retains its warning; source-adventure creation retains `cover_from` handling | Creation handlers and payload construction match `main`; existing configuration owners remain in use. |
| Editor navigation | All 15 sections, sequence counts and validation status; Visual Novel mode continues to omit Side Quests and Awards | The navigation component receives the original filtered tab list and uses the existing `activeTab` state. |
| Entity fields | Names, descriptions, identifiers, traits, goals, state, equipment, inventory, item properties, visibility rules and scripts | The restructured entity editor retains all 124 `v-model` and event-handler directives from both `main` and the pre-grouping source. No binding or handler expression was removed. |
| Conditional fields | NPC/protagonist and item-type conditions, nested rule controls and `v-if`/`v-else` pairs | Template compilation succeeds. New group conditions repeat restrictions already present on their children. |
| Saving and cancellation | Existing entity payloads and identifiers, saved values after reopening, retained values between tabs, discard without writing | `authoringDialogChecks.mjs` exercises NPC and readable-item editing through the real editor components. |
| Validation | Invalid required fields disable saving; identifier errors remain visible outside the collapsed identifier section | The existing validation owner and save guard are unchanged. Narrow-screen checks include invalid identifiers and collapsed sections. |
| Map and routes | Scene and exit routing, directional connections and arrow markers | `authoringChecks.mjs` checks the actual map markers. Scene/exit handlers and route state remain owned by the editor. |
| Entity bundles | Existing export and import services, `.twe` selection, direct NPC/item import, protagonist replacement confirmation | `entityTransferConfirmation.test.mjs` and `authoringImportChecks.mjs` cover accept, cancel, Escape, backdrop, focus return and file-picker activation. |
| Responsive layout | Reachable editor sections, scrolling bodies and action footers | Browser checks cover narrow mobile screens and a 720×500 layout representing the available space of a 1440×1000 screen at 200% zoom. |

The sections retained are World, Living World, Sequences, Protagonist, Map,
Scenes, Inhabitants, Items, Side Quests, Awards, Scripts, Visual Style, Tone,
Advanced and Validation.

The creation and editor business scripts were compared directly with `main`.
Before the explicit protagonist-confirmation enhancement, they matched after
removing theme imports/calls and the extracted navigation import. Entity-editor
business logic still matches after removing the field-group component import.
The grouping changes reorder existing controls rather than replacing their state.

`adventureService` remains the owner of adventure metadata, assets, validation
and scripts. `entityService` remains the owner of scene/exit operations, entity
updates and bundle transfer. Existing authorization and configuration checks are
retained; the interface does not substitute for server authorization.

## Other reviewed interface boundaries

| Area | Review focus and coverage |
| --- | --- |
| Chat actions and header | Grouped actions retain their original events and visibility conditions. Checks include grouped menus, keyboard interaction, header layout, portrait spacing, mobile controls and Visual mode. |
| Session settings and NPC cards | Existing settings, personality details, equipment/state and history remain available. Refined card presentation uses the existing data. General overview stays independently collapsible. |
| Language and typography | Bable Fish continues to save session content language. Font selection follows the confirmed language; leaving the session restores the prior typography scope. Local font files retain licenses and checksum manifests. |
| Portal and administration | Library/session actions, grid/table views, intelligence settings and role restrictions remain connected to their existing owners. Shared menus and dialogs are checked for clipping, scrolling and keyboard use. |
| Attribution and licenses | Original developer and fork attribution are separate. The license catalog loads full local texts, and downloads use the displayed text. License and font checks verify vendored files and provenance. |
| Sign-in and recovery | Login uses an unchanged copy of the README artwork, preserves its aspect ratio and identifies Jean Schmitz as original developer and Anton Kuprin as fork creator. Authentication and recovery handlers are unchanged. Responsive checks cover password visibility, errors, cancellation, remembered username, successful sign-in and recovery, and the shared license dialog. |

## Fixes checked during the review

- Authoring background and NPC toolbar overflow on narrow screens.
- Table/action-menu clipping and shared popup positioning.
- Dialog spacing, bounded scrolling and reachable action footers.
- Nested script-editor fullscreen presentation.
- Protagonist import confirmation now follows the workspace theme while keeping
  file selection synchronous with the confirming click. Canceling or changing
  adventures does not open a picker.
- Collapsed identifier fields retain a visible validation summary.

Some layout defects already existed in the previous interface and were exposed
while checking the new presentation. Their correction does not change the
underlying adventure or session mechanics.

## Verification entry points and limits

Run the full frontend unit suite before publishing:

```sh
cd frontend
node --test tests/*.test.mjs
npm run build
```

Relevant browser entry points include `authoringSmoke.mjs`,
`scriptEditorLayoutSmoke.mjs`, `portalWorkspaceSmoke.mjs`,
`adminRefinementsSmoke.mjs`, `groupedActionsSmoke.mjs`,
`refinedCharacterSmoke.mjs`, `sessionSettingsLayoutSmoke.mjs` and
`sessionTypographySmoke.mjs` under `frontend/tests/browser/`.
`loginLayoutSmoke.mjs` exercises the real sign-in components against intercepted
fictional authentication routes; authentication payloads are redacted in fixture
request records.
Unit coverage includes `entityTransferConfirmation.test.mjs`,
`workspaceTheme.test.mjs`, `sessionTypography.test.mjs` and
`licenseCatalog.test.mjs`.

Browser fixtures contain fictional data and intercept API requests. They verify
component behavior, request contracts and presentation without paid model calls.
They do not establish live-model output quality, live provider compatibility or
production database behavior. Existing backend language tests cover the changed
language fallbacks separately.
