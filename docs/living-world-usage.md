# Living World · Experimental

Living World keeps bounded NPC routines and private memories in the saved session.
It is opt-in. The original rules-only mode remains available without any model calls.
Private decisions can use TaleWeaver's native engine or the optional Concordia 2.4
sequential engine. Neither runs a perpetual agent swarm or a second RAG database.

## Setup

1. Update dependencies with `poetry install` and `npm ci` in `frontend`. Apply the
   migrations with `poetry run alembic upgrade head` (normal startup also applies
   them), including the adventure defaults column.
2. For model decisions, set `INFERENCE_SERIALIZATION_ENABLED=true` in `.env` and
   restart the backend. Configure the **Utility** model with **Ollama** or
   **OpenAI-Compatible API**. These are the transports covered by the shared
   inference reservation. Provider credentials and timeout use existing settings.
3. Open a session's settings → **Living World · Experimental**. Enable Living World.
   **Pause while away** never converts wall time into game time; **Catch up when
   returning** preserves the unprocessed absence backlog.
4. Enable **Allow bounded NPC decisions**. Enable **Schedule recurring NPC decisions**
   to generate small routines automatically; otherwise only explicit API events run.
5. Choose budgets and save. Enable **Run automatically while playing** to start
   bounded background batches from presence heartbeats; **Continue catch-up** remains
   available for manual processing. The optional return setting applies when automatic
   processing is off. Heartbeats continue while inference waits.

### Adventure defaults for VN

When creating or editing an adventure, select **VN** and open **Living World**.
The **Enable Concordia** checkbox reveals time controls, recurring NPC routines,
and request and processing budgets. Every control has a small **?** button with
help on hover, keyboard focus, or tap. Apply the settings when creating an
adventure; the editor's **Save settings** also saves the adventure changes.

These defaults are copied into **new sessions only**. Existing sessions retain
their own settings and memories; change those through the session settings.
Turning Concordia off retains the chosen budgets but disables Living World and
NPC deliberation for new sessions. Copies and adventure exports preserve defaults,
without copying a session's private simulation journal.

The window reports missing Concordia or shared inference serialization. Defaults
can be saved before server setup, but model decisions require the setup below.
The Utility model supplies the provider, credentials, and global LLM timeout.

### Optional Concordia

Use Python **3.12 or 3.13** and install the pinned optional extra:

```sh
poetry install --extras concordia
```

The normal dependency set still supports Python 3.10/3.11 without Concordia.
Selecting Concordia without the compatible package returns a configuration error;
there is no silent fallback to the native engine and no runtime package download.
Keep specifying the extra on subsequent dependency installations.
The stock Dockerfile uses Python 3.12 and supports the native decision engine.
Build with `docker build --build-arg INSTALL_CONCORDIA=true -t taleweaver-concordia .`
to include the optional Concordia package. It is not installed in the default image.

The setup scripts accept `./setup.ps1 -Concordia` (Windows) and
`./setup.sh --concordia` (Linux/macOS). Both verify the installed version. Restart
the backend, refresh session settings and choose **Concordia 2.4**.

Concordia executes one real `Sequential.run_loop(..., max_steps=1)` per decision.
Its NPC entity receives a local observation, acts through TaleWeaver's async model
router, and submits a proposal to the deterministic game master. The GM does not
make extra LLM calls. SQL validation and timeline fencing remain the final authority.

## Automatic play and concurrent inference

**Run automatically while playing** checks for due work while the session tab is
visible, at the configured interval (20–600 seconds, default 60). Heartbeats arrive
about every 20 seconds, so this is an approximate minimum interval. Only one batch
per session runs at a time. Closing/hiding the tab stops new batches; an already
started request can finish. Other open tabs can keep the session active.

The game clock follows narrated events. Reading or typing for a long time does not
advance the fictional scene. Offline Catch up is still controlled separately.
NPC actions and private notes are consumed by subsequent narration; the simulation
does not insert extra chat replies. Automatic mode lets foreground play continue
without requiring manual backlog processing; stale model replies are discarded.

By default, decisions wait for a quiet inference opportunity. **Allow concurrent
LLM requests** permits one Living World request alongside the normal endpoint
request (two maximum across those lanes). Enable it only if the model server supports
parallel requests and has sufficient resources. It does not make the server parallel
by itself. Both slots retain durable timeout/crash fences; an uncertain request
blocks new admission until administrator recovery. SQL writes remain serialized.

**Stop after current event** pauses automatic scheduling in this backend process.
Failures also pause it rather than repeatedly consuming attempts. See the status
and error in session settings; **Continue catch-up** retries and resumes automatic
processing. Saving settings also clears this runtime pause. Restarting the backend
clears runtime pauses, but preserves settings, events and spent request budgets.

## Choices during player conversations

**NPC choices in important conversations** optionally adds one Utility-model request
before narration at recognized conversational branches. The initial trigger supports
English/Russian requests, offers, promises, trust questions and choices. It requires
one unambiguous present NPC (named in the message, or the sole present NPC); ordinary
chatter and ambiguous group conversations are skipped. This conservative trigger
is not a semantic classifier for every language or possible phrasing.

The NPC receives its character description, its own private notes, at most three
committed observations and the current player request as an unverified statement.
The chosen stance is accept, refuse, negotiate, evade, ask for clarification or defer,
with a short private motive and intention. Concordia uses one sequential step when
selected; the native engine can also produce the same structured choice.

The result is turn-local guidance for narration, not an executed action or a RAG fact.
It cannot force the player or override mechanics. The extra request uses the Utility
timeout and shared timeline allowance, adds latency, and runs before narration even
when concurrent background requests are allowed. Invalid output falls back to normal
narration without inventing a choice. Existing saved settings keep these new options
off until enabled; newly configured adventure defaults enable automatic processing
and conversation choices, while concurrent requests remain off.

## What NPCs can do

- **Wait**, **move** through an available adjacent exit, or **talk** to an available
  NPC in the same location. A social event is one speaker's line, never an invented
  response from the other NPC. Subsequent decisions can answer that line.
- Routines rotate a bounded cohort of NPCs at configured game-minute intervals.
  Only the next slot is compiled; remaining offline time is not discarded. Routine
  decisions do not trigger player traversal scripts or resolve scripted obstacles.
- Each NPC has one short current goal, one explicitly unverified belief, and up to
  eight observations sourced from committed simulation events involving that NPC.
  They do not receive other NPCs' private notes, the full world plot or the chat log.
- A spoken assertion is stored as **“NPC said …”**, not as a verified claim about
  the world. Proposed moves, rejected output, plans and beliefs never enter RAG.
- Narration receives private motivations and at most two recent observations for
  each of up to three present NPCs, capped
  at 1,800 JSON characters plus a short boundary instruction. It is told that beliefs
  can be wrong and goals are not completed actions. The full journal is never added.

This is a bounded social simulation, not a replacement for the adventure's quest,
combat, inventory or scripting systems. It does not add arbitrary items, teleport,
force player actions, or automatically infer changes in relationships from a line.
Existing narration and image-generation settings retain their own instructions.

## Budgets and recovery

| Control | Bound |
| --- | --- |
| Rules work | Shared event/game-hour/rules-wall-time budget across the whole batch |
| Model work | 1–4 decision attempts per Continue/reconnect batch |
| Timeline allowance | Default 8, adjustable 0–128 attempts; failed/stopped attempts count |
| Per-event retries | At most two attempts; no automatic malformed-response retry |
| Output | 128–1,024 tokens requested, capped by the Utility model's own limit |
| Deadline | Utility model timeout, including queue wait; browser adds no shorter deadline |
| Private state | At most 128 NPCs, one goal/belief and eight observations each |
| Event journal | 512 events; capacity errors never silently prune committed history |

An attempt is charged before queue admission, so the displayed count is not a
provider billing/token-usage meter. Raise the timeline allowance explicitly if needed.
At a hard limit, disable the experiment to continue ordinary play or restore a
checkpoint. There is no unlimited budget reset endpoint.

**Stop after current event** also cancels a pending decision and discards its reply.
Already-running remote inference may continue on the provider. An uncertain request
keeps the shared endpoint fenced until administrator recovery; see
[inference-queue.md](inference-queue.md). No SQL transaction or session write lease
is held while waiting for inference. Once admitted, remote background work cannot
be preempted safely; later foreground calls may have to wait for it to finish.

Changing the world, disabling the feature, importing, copying or rewinding while a
response is pending invalidates it. Ownership, state fingerprint and timeline are
checked again before applying anything. Crash/retry never commits a late answer.
The supported deployment remains one backend worker.

## Privacy and saved games

Administrators who own a session can open **Private simulation journal**. Normal
status responses and character cards do not expose these notes. Exports contain
private simulation state for restoration, so treat them as private backups.
Chronicles and full-turn replay restore notes and events atomically and fork the
timeline. Copy/import also fork timeline identity. Presence and remote-inference
reservations are deliberately not rewound with the fictional world.

## API

All routes are under `/api/adventures/{session_id}/living-world` and require the
existing authenticated owner. Revision-bearing commands reject stale requests.

| Method / suffix | Purpose |
| --- | --- |
| GET base | Public status, budgets, runtime adapter availability |
| PATCH base | `{settings, expected_revision}` |
| POST `/presence` | `{client_id, active}`, independent of model work |
| POST `/resume` | `{expected_revision}`, bounded rules only |
| POST `/deliberate` | `{expected_revision}`, resolve the next due decision once |
| POST `/cycle` | `{expected_revision}`, bounded rules + decisions + routines |
| POST `/stop` | Stop the active rules/model batch |
| GET `/events` | Administrator-only event and private-note journal |
| POST `/events` | Administrator-only unexecuted event proposal |

Example explicit schedule (POST each event separately, with real session NPC IDs):

```json
[
  {"event_id":"lili-plan","due":60,"kind":"DECISION","actor":"LILI"},
  {"event_id":"mirinda-plan","due":60,"kind":"DECISION","actor":"MIRINDA"},
  {"event_id":"lili-talk","due":61,"kind":"SOCIAL","actor":"LILI","participant":"MIRINDA","dependencies":["lili-plan","mirinda-plan"]}
]
```

This schedule does not guarantee a meeting: decisions and world validation still
control positions. If the participants are apart, a social decision may wait; it
cannot fabricate co-presence. For automatic routines, no API scheduling is needed.

## Verification

```sh
poetry install --extras concordia
poetry run pytest tests/test_living_world*.py tests/test_inference_reservations.py tests/test_inference_integration.py -q
poetry run mypy backend/engine/living_world backend/api/routes/adventures/living_world_decisions.py --follow-imports=silent
cd frontend
node --test tests/*.test.mjs
npm run build
```

The two-NPC acceptance test runs against both the native and **real installed
Concordia engine**. Controlled model replies move both NPCs, exchange two lines,
maintain distinct beliefs, verify RAG isolation, export state and rewind Chronicles.
Concurrency tests cover another SQL writer during inference, stale replies,
duplicate requests, cancellation-resistant responses and stopped/invalid attempts.
CI includes a separate optional-Concordia job; default installations skip only the
Concordia-specific acceptance cases.

For the Chromium UI smoke test, start Vite on port 5179 and run
`node tests/browser/livingWorldSmoke.mjs` with Playwright available. Set
`PLAYWRIGHT_MODULE` to its module path and `CHROMIUM_PATH` to a local browser when
needed. The test uses actual Vue controls and controlled API responses for save,
engine selection, cancellation, error recovery and the private journal.

Automated acceptance uses controlled model replies, not a live GPU or commercial
API. Real-model narrative quality, hallucination rate and hardware latency still
need playtesting. The feature therefore remains **Experimental**.
