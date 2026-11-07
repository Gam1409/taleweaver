# Repair and retry actions

Failures in a repair preview or capability check must leave a visible next action.
These actions are explicit; they do not start a model call automatically.

- **AI Fix:** findings from structural checks and AI validation both offer AI-Fix.
  Empty results offer **Generate fresh suggestions**. An error offers **Retry**.
  Both ask for new suggestions, bypassing the previous proposal cache. Reviewing
  and applying remain separate actions, and an empty result cannot be applied.
- **Turn regeneration:** a failed snapshot check offers **Retry turn check** in
  both action-bar layouts. This only reads replay availability; it does not generate
  text or change the session. Replay respects evaluation and input locks.
- **Debug item repair:** a failed initial load offers **Retry loading item**.
  **Reload saved item** refreshes the item's fingerprint after a stale-preview
  rejection. It asks before discarding an existing draft and clears the old image
  preview only after a successful reload. Canceling or failing to reload keeps the
  draft. Nothing is saved until **Apply selected sections** succeeds.
- **Manual Vision Weaver:** prompt suggestions and image generation share one
  request slot. Closing or aborting the dialog, changing its target or adventure,
  and unmounting invalidate the request. A late response cannot replace a new
  target's prompt, close its dialog or unlock its request. Provider errors appear
  inside the dialog, keeping the prompt available for retry. Abort cancels the
  browser request; it does not prove the remote model has stopped computing.
- **Batch image generation:** provider errors count as failed images, rather than
  successful generations. A superseded quick-generation request cannot remove
  the newer request's cancel handle or clear its busy indicator.
- **Editor assets:** only the latest refresh for the currently selected adventure
  may replace world assets. An older failure cannot erase a newer successful load.

Regression coverage:

```sh
cd frontend
node tests/recoveryActions.test.mjs
node --test tests/*.test.mjs
```

`tests/browser/recoveryActionsSmoke.mjs` mounts the real components in Chromium
and supplies controlled HTTP failures through Playwright. It covers visible
actions, input locks and cancel/confirm reload. It does not establish live-model
quality. `tests/test_ai_fix_workflow.py` and `tests/test_item_repair.py` separately
cover the real backend routes and persistence using isolated SQL and model mocks.
`tests/manualVisionLifecycle.test.mjs` covers overlapping requests and late
completions; `tests/browser/manualVisionSmoke.mjs` verifies cancellation reaches
HTTP and a failed prompt suggestion can be retried from the same dialog.
