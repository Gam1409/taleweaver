# Post-generation validation and auto-fix

The **Validate & auto-fix after generation** checkbox is available in both world
creation forms and defaults to enabled. Turn it off to skip this extra pass.

After the world is generated, the existing editor validator checks it. The fixer
attempts at most 12 findings, prioritizing errors, and applies the first proposed
patch for each. The initial playable session is materialized after this pass so
it includes the applied changes. Validation failure does not discard the world.

The generation progress view now shows a persistent summary: initial findings,
applied fixes, and unresolved findings, with up to five examples in each group.
A skipped AI check or failed validation is shown explicitly. Full validation
information remains available in the editor's Validation tab. Applied patches
are not a guarantee that every narrative problem is solved; rerun validation in
the editor to assess the resulting world.

The limit is 12 findings, not 12 total network requests: validation, retries and
provider fallback can add calls. Local model latency therefore affects the total
wait. Existing role-specific model/URL settings and request timeouts still apply.
The existing validation and fix context retain the adventure language.

This ports the reporting/UI improvements from upstream commits 80fac70 and
8673a59; the base auto-fix pipeline and opt-out already existed in this fork.
