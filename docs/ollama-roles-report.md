# Ollama role implementation report

Base: `3641ff71ef6ed17265d5d28bdce2863987f4cb92`. Branch: `feat/ollama-role-settings`, stacked on the earlier custom OpenAI-compatible endpoint feature. No dependency lock file or database schema changes.

Implemented all five roles, the shared provider/model resolver, migrated callers, role-specific discovery and unsaved connection tests. See [configuration and the 30-location audit](ollama-roles.md).

## Validation

- Initial five-file regression baseline on this checkout: **70 passed** (the specification's 63-test baseline refers to a different revision).
- Final focused regression: **258 passed**, including all five roles, same/different endpoint pairs, settings, retries, agent mode, security, compression, custom OpenAI compatibility and both Ollama wire transports.
- Full `pytest -q`: **914 passed, 14 failed** in 686.86 seconds. Four failures were stale constructor/stream fixtures, corrected and verified in subsequent focused runs. The other ten reproduce on the untouched base snapshot; see the list below. The full suite is not green.
- Ruff across all modified Python files: **114 baseline diagnostics → 98**, **zero new**. Existing complexity/security diagnostics were not suppressed. New Python modules and tests pass Ruff. `ruff format --check`: **40 files passed**.
- Matched fresh mypy runs (`--no-incremental`) on changed backend modules: **1688 baseline errors → 709**, **0 new**. Counts include imported modules; errors are compared by file/message while ignoring shifted line numbers.
- Frontend: `npm install --package-lock=false --ignore-scripts --cache /workspace/.cache/npm` and `npm run build` passed. Lock files remain unchanged. New Vue/TypeScript modules pass ESLint.
- Chromium component/service check: five role panels, five isolated model lists, correct URL for each discovery request, correct role/URL in all five Test payloads, cleared numbers sent as `null`, and no browser errors.
- Local fake-server comparison: `ollama` and `ollama_chat` both passed all five request paths. Both send `options.num_ctx=8192` and `options.num_predict=777`, with Pydantic schema in `format`. The chat variant preserves message roles. The saved API mode selects either transport; Generate remains the compatibility default. Actual timeout tests on both transports verified four attempts against a slow local HTTP server.
- Real browser/API check against the replacement RunPod endpoint: **three save/reload rounds passed for all five roles**, including model swaps, separate role URLs, timeout/context settings, Generate/Chat mode and visibility from a second user. No browser errors. Screenshots are available in the separate [`docs/ollama-settings-preview`](https://github.com/Gam1409/taleweaver/tree/docs/ollama-settings-preview/docs/screenshots) branch.
- Generated-session initialization: **3 tests passed** after the final type-only adjustment; the earlier session/lifecycle/security run passed 25 tests. A generated world now starts in a real generated scene instead of retaining the placeholder `START` when the generator chose different scene IDs.
- Real inference reached both user-provided models. The original network restriction was resolved. Detailed live results follow below.


## Integration with main (`518f0d4`)

The five merge conflicts were resolved while retaining main's extracted settings normalization, Play Agent personality controls, manual model-selection state and frontend dependency/Vite checks. Ollama and custom OpenAI defaults now live in `settings_normalization.py`; explicit empty Ollama models and per-role overrides remain preserved.

Manual model selection uses each role's endpoint-specific model list. A JavaScript automatic-semicolon-insertion error in the incoming selection handler was also corrected: selecting a discovered model after custom input no longer attempts to call `false` as a function.

- Initial targeted backend run: 257 passed, 2 failed because new Play Agent tests still mocked the old constructor. Both mocks were migrated to the role-aware factory. Those two tests and the expanded settings round-trip test subsequently passed (3 passed). All 259 cases from that targeted suite are covered by these runs.
- Broader settings, agent, game-loop, compression, security and adventure-lifecycle run: 193 passed, 4 failed. One was the expanded test fixture missing explicit private-endpoint opt-in; the corrected fixture passed in the rerun above. The remaining three game-loop failures were independently reproduced on an untouched export of main at `518f0d4`: deterministic quest-completion messages, NPC stamina logic and quest XP accumulation. The full suite is still not claimed green.
- Ruff and formatting checks passed for all eight manually resolved or automatically merged Python files inspected in this integration.
- PowerShell: 22 assertions passed, including missing Vite detection, explicit `npm install --include=dev`, successful setup and `SkipStart`. Native Windows process-window launch remains unverified.
- Final frontend build passed; ESLint reported no errors and two existing unused-variable warnings. Chromium checks passed for all five role model lists and Test payloads, custom/discovered model selection, URL copying, independent overrides, save/reload, collapsed accordions and keyboard toggling.
- No additional live inference, world generation or SSH tests were performed during conflict resolution. Earlier live-model limitations below remain applicable.

## Follow-up: the three game-loop failures are resolved

These failures were reproduced with mocked LLM output; they were not evidence of model context loss.

- The two quest tests expected obsolete `Quest completed:` / `you gained ... XP` text, while the application stores `Side-quest completed: ... (+... XP)`. Their shared fixture also omitted the `GameSession` row, causing checkpoint persistence to raise `Session not found`. The fixture now creates a complete session, and the tests verify current notifications, checkpoint events and absence of pipeline errors. The XP test repeats the model's completion suggestion and verifies that neither the reward nor the notification is duplicated.
- The combat test exposed a code defect: refreshing `SessionState` expires its `session` relationship, but a reused turn manager skipped loading it again. Reading it synchronously raised SQLAlchemy `MissingGreenlet`. Initialization now explicitly awaits loading that relationship when it is unloaded. Regression cases cover active, completed and game-over sessions, including input locking after the epilogue.
- The repository state inspector confirmed the missing session in the original test snapshot. After correction, inspected snapshots contain the completed quest and its notification, and the exhausted NPC's stamina has recovered to 20.
- Validation: **142 passed** across the full game-loop suite, session-loading regressions, win/loss guards, agent mode, security hardening, quest awards and sequence rules. Ruff and formatting passed for all three modified Python files. The complete repository suite was not rerun; unrelated historical failures and live-model limitations remain outside this result.

## Live-model observations

Models: `hf.co/mradermacher/Qwen3-14B-Uncensored-GGUF:Q6_K` for small, generator, compression and play_agent; `hf.co/mradermacher/Artemis-31B-v1.2-abliterix-v2-GGUF:Q6_K` for complex narration. Live tests used isolated local users and a temporary database. Image generation and voices were disabled.

- The first ten-call comparison exposed a RunPod HTTP 524 on non-streaming generation and empty or reasoning-only Artemis narration. These are failures, despite some successful HTTP responses.
- After explicitly passing `think=false`, 29 repeated calls produced 24/24 successful Qwen responses (four roles × two modes × three repeats). Artemis Chat produced useful narration 3/3 times; Generate produced useful narration once, then failed. The Generate series stopped after that error. Qwen's median elapsed time was 2.38 seconds for Generate and 1.99 seconds for Chat; cache and warm-up effects limit this comparison.
- Both modes sometimes emitted a reasoning prefix ending in `</think>` without an opening tag. Non-streaming cleanup now removes that prefix. The server's model template can still affect thinking behavior.
- A real small world completed with three scenes, one NPC and one item in 166.5 seconds. This required a **test-only adapter that streams structured responses and aggregates them before the application's normal parser**; the production structured-call transport remains non-streaming. Its preceding non-streaming request received HTTP 524 at about 126 seconds. Raising the configured role timeout cannot override the proxy limit.
- Three full gameplay turns completed in 50.85, 86.27 and 124.34 seconds. A valid transition from the village to the forest occurred. The next turn **failed the coherence check**: the stored location remained the forest while narration described reaching the keeper and interacting with a key. Unexpected health/stamina restoration also appeared. Actual requests used the configured Qwen/Artemis roles; correct routing did not prevent model or pipeline errors.
- Actual compression requests were observed during gameplay, using the compression role's Qwen model, timeout and context settings.
- The first rich-world attempt ended with an incomplete response stream around 600 seconds while the user reported resetting server settings. That interrupted attempt is not evidence of completed generation or of Qwen's reasoning quality.
- After the replacement endpoint was configured and the three browser rounds passed, the rich-world retry reached **12,288 completion tokens** and failed with the application's explicit truncated-response error. The model response took 649.14 seconds; the job reported failure after 653.63 seconds. It did not produce a playable world. The request used Qwen, Chat, `think=false`, `num_ctx=32768` and a 600-second request timeout. The test-only streaming transport continued receiving data beyond 600 seconds: this timeout is not a hard total-duration limit for that streaming adapter.
- Direct SSH to the supplied exposed endpoints and to the RunPod SSH gateway returned connection refused from this cloud environment. The uploaded key pairs matched, but SSH authentication was never reached. A user-managed localhost tunnel is documented; end-to-end tunnel testing remains unverified.

## Paused live validation

The user requested that live testing stop and the current work be pushed to GitHub. The isolated live-test server was stopped. The detailed-world inventory/equipment audit, ambiguous-action scenarios, further NPC/item/location transitions and a complete live autonomous-agent turn remain **unfinished**. All five unsaved Test payloads and non-persistence are covered by automated tests; a fresh five-role live Test-button inference run against the replacement endpoint was prepared but not executed. Do not interpret the successful configuration checks or small-world turns as a pass for those pending scenarios.

The rich-world prompt also requested bracers in an `Arms` slot, whereas the application's equipment schema uses `Hands`. Correct that test input before the next retry; no equipment result was produced in this failed run.

## Existing full-suite failures

All ten reproduce on the original base code:

- `test_adventures_api.py::test_import_adv_preserves_consumable_effects_in_avatar_inventory`
- `test_adventures_api.py::test_chat_snapshot_inventory_readable_uses_text_log_content`
- `test_adventures_api.py::test_start_session_honors_manifest_start_scene_id_when_graph_has_no_entry`
- `test_consequences_and_rumors.py::test_apply_game_event_memories`
- `test_consequences_and_rumors.py::test_apply_game_event_duplicate_memories`
- `test_dynamic_items.py::test_debug_commands_toggle_rejected_and_drops`
- `test_game_loop.py::test_deterministic_quest_completion_marks_inactive_quest_and_emits_system_message`
- `test_game_loop.py::test_combat_npc_stamina_logic_active`
- `test_game_loop.py::test_quest_completion_accumulates_xp`
- `test_generation_stabilization.py::test_clean_stream_voice_tags`

These include outdated adventure fixtures, missing mock state, asynchronous SQLAlchemy access and existing gameplay/stream assertions. They were not changed as part of the routing work.

## Behavior and limits

Explicit cloud provider/model choices and default cloud model names remain supported. Pair inheritance intentionally corrects inconsistent legacy fallback chains: when a role borrows a provider, it also borrows that role's model. An explicit Ollama selection with an empty model survives settings normalization and produces a clear configuration error at resolution time. Distinct editor candidates are no longer deduplicated solely by provider/model when their role endpoints may differ.

Chat is now an opt-in setting, assessed against the user's real models. Successful routing does not establish gameplay correctness. Global URL SSRF validation, the environment cloud fallback in AI-fix, proxy/watchdog time limits, and strict JSON reliability remain documented limitations in the configuration guide.

## Changed files

- `README.md`
- `backend/api/routes/adventures/agent_logic.py`
- `backend/api/routes/adventures/assets.py`
- `backend/api/routes/adventures/combat/narration.py`
- `backend/api/routes/adventures/editing/ai_fix_llm.py`
- `backend/api/routes/adventures/editing/generation.py`
- `backend/api/routes/adventures/editing/validation.py`
- `backend/api/routes/adventures/gameplay.py`
- `backend/api/routes/adventures/gameplay_logic.py`
- `backend/api/routes/adventures/guardrails/base.py`
- `backend/api/routes/adventures/session_materializer.py`
- `backend/api/routes/adventures/session_start.py`
- `backend/api/routes/adventures/templates.py`
- `backend/api/routes/adventures/turn_adventure_gen.py`
- `backend/api/routes/adventures/turn_context_helpers.py`
- `backend/api/routes/adventures/turn_suggestions.py`
- `backend/api/routes/config_api.py`
- `backend/api/routes/users_api.py`
- `backend/core/llm_roles.py`
- `backend/core/llm_router.py`
- `backend/core/ollama_role_config.py`
- `backend/engine/world_generator.py`
- `docs/ollama-roles.md`
- `docs/screenshots/llm-settings-roles.png`
- `docs/screenshots/llm-settings-endpoints.png`
- `frontend/src/components/admin/IntelligenceSection.vue`
- `frontend/src/components/admin/OllamaRoleSettings.vue`
- `frontend/src/services/ollamaRoleSettings.ts`
- `frontend/src/services/settingsService.ts`
- `frontend/src/services/testService.ts`
- `frontend/src/views/AdminView.vue`
- `tests/llm_fakes.py`
- `tests/test_agent_mode.py`
- `tests/test_ai_fix_endpoint.py`
- `tests/test_combat_specials.py`
- `tests/test_config_api.py`
- `tests/test_custom_openai_connection.py`
- `tests/test_dynamic_items.py`
- `tests/test_game_loop.py`
- `tests/test_guardrails_behaviour.py`
- `tests/test_history_compression.py`
- `tests/test_key_item_mention.py`
- `tests/test_llm_roles.py`
- `tests/test_llm_router.py`
- `tests/test_npc_logic.py`
- `tests/test_ollama_transport.py`
- `tests/test_session_start.py`
- `tests/test_prompt_suggestions.py`
- `tests/test_validation_endpoint.py`
- `tests/test_validation_persistence.py`
- `docs/ollama-roles-report.md`
