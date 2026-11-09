# Session integrity review repairs

The review baseline is `0eb76d04`. Changes are delivered in separately verified
waves. Model responses in regression tests are mocked; live Pods are offline.
Passing these tests establishes host contracts, not model reasoning quality.

## Wave 1: narration and foreground ownership

- Reject known incomplete regeneration before replacing the saved response.
- Extend the existing writer lease through the entire Play-Agent cycle and its
  settings updates. Explicit capability delegation allows the nested narration
  turn to use that same lease, without granting background tasks implicit access.
- Bind agent and terminal epilogue responses to their originating session,
  request controller and snapshot revision. Navigation aborts those requests.
  Final agent history reload keeps input locked until it finishes.
- Reuse the frontend lifecycle harness across chat and ownership regressions.

The original review's remaining work covers independent scene-delta validation,
clothing/provenance contracts, NPC host facts, source retraction, history polling,
causal projections, diagnostics and structured technical model requests.
