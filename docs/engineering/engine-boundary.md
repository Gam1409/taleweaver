# Turn services and the API boundary

Gameplay implementation lives in `backend/engine/gameplay/`: the turn manager,
world/session resolution, combat, guardrails, play-agent and turn handlers.
HTTP routes import these services. Engine modules must not import API routes,
including lazy imports or imports used only for typing. The architecture test
enforces this rule across the entire engine directory.

The route layer retains dependency injection, HTTP request parameters and route
registration. Shared unlock actions and their payload contracts are reusable by
both endpoints and the play-agent. Living World orchestration and ownership/
revision checks serve both routes and idle workers. Image request contracts,
visual prompt composition and global-settings lookup also have transport-independent
homes. STT no longer imports private helpers from the settings route.

Old gameplay implementation paths remain compatibility facades. A module facade
resolves to the same implementation object, preserving class identity and existing
import-based integrations. New code must use the canonical engine paths. Do not
add business logic to those facades. HTTP endpoints keep their existing URLs and
payload shapes; this source relocation does not change saved schemas.

The legacy manager is still large. Moving it is an import-boundary correction,
not evidence that its Pass 1/1.5/2 orchestration has become simple. Subsequent
decomposition must preserve trigger order, turn receipts, script reentrancy,
combat and rollback behavior with the complete integration suite. No feature
should add more branches to that existing orchestration method.
