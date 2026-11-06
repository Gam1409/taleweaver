# Dependency security checks

The security workflow audits the exported Poetry runtime, development dependencies
and optional extras, plus the complete npm lockfile. It runs on dependency changes,
pull requests, a weekly schedule and manual dispatch. Audit failures retain their
exit status and reports are uploaded; there is no advisory ignore list.
CodeQL separately analyses Python and TypeScript/JavaScript. Dependabot opens
weekly update proposals; publishing still requires the normal test checks.

The November 2026 refresh updates Pillow, certifi, aiohttp, filelock,
OpenTelemetry and Black, and updates Vue, DOMPurify, Vite and frontend tooling.
Pillow 13 requires Python 3.11, which is now the application minimum. Desktop,
Docker and CI use Python 3.12; Concordia remains optional and requires 3.12+.

ESLint now uses its supported flat configuration. Its previous baseline checks
are preserved; the migration does not enable every TypeScript recommended rule.
Unused template references and stricter template iteration types were corrected
rather than suppressing errors. The scoped npm override upgrades
`@typescript-eslint/typescript-estree`'s minimatch to 11.0.1 or later to fix
GHSA-g3hv-75wg-m249; other minimatch majors are unaffected. Remove the override
when upstream adopts a fixed version. Full lint, types, tests and build check
this tooling combination.

A clean advisory scan is time-dependent evidence, not proof that software has
no vulnerabilities. Review new findings for reachability and fixes; do not hide
them by disabling the workflow or automatically accepting major upgrades.
