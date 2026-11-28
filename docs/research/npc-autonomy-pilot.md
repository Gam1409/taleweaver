# NPC autonomy pilot

**First question:** if a resident chooses to leave while the player is occupied,
does that choice survive execution? Living World already schedules decisions,
projects actor-local evidence, retains private goals and validates routes before
commit. Its recent-chat courtesy rule can defer and eventually abandon a move.
In session Living World settings, enable bounded NPC decisions and toggle
**Allow NPC-chosen moves during an active conversation**. Off is the legacy
control. Only new deliberated moves use this switch. Physical availability,
route locks, inference fencing and previously deferred events retain their rules.
The paired API test holds the decision fixed and checks persisted position.

**Second question:** what does a model actually choose? Run the separate
synthetic workshop with a local OpenAI-compatible endpoint:

```sh
poetry run python -m scripts.npc_autonomy_pilot --base-url http://localhost:5001/v1 --model MODEL --ticks 3 --repeats 1 > pilot.jsonl
```

This smoke run makes 45 sequential requests (three residents × five arms ×
three ticks). No retry or judge requests. Transport errors stop the run;
invalid replies consume their opportunity. For the behavioral comparison use
eight ticks and three repeats; repeat with `--swap-projects` to exchange only
Lina's and Ren's initial projects. Keep the model, sampling, world, actor order
and output budget fixed. A server may ignore seeds. Game time advances in steps;
this runner uses no real session, production narrator or wall clock.

| Arm | Change from previous arm |
| --- | --- |
| reactive | Visitor-oriented prompt; same opportunities and projects. Prompt control, not the production game. |
| resident | Resident-oriented prompt; same world observations. |
| remember | Also return the actor's last private intention as input next time. |
| skills | Expose recent successful primitives; the model may name, save, revise and invoke its own two-to-four-step routines. |
| open | Also permit inventing destinations and replacing the initial project. A named destination is a shared place, not a generated map or a teleport in the actual game. |

At tick zero the visitor is absent. At tick one the visitor asks for a chat in
the studio; at tick two they are silent; then they leave. Each resident gets one
action per tick. An approach to another NPC is observable to the recipient; it
does not prescribe a reply. A routine costs one turn per primitive and may stop
or fail. Each trajectory starts with an empty private notebook. No weights change.

Read the JSONL for visits, completed work (three committed steps), interruption
and resumption, repeated invalid moves, NPC–NPC contact and successful skill
reuse. Count abandoned projects separately from completions. Compare calls,
tokens when reported and latency. Count silence, cooperation and refusal as
choices rather than rewards. Verify whether changed interests change trajectories;
do not infer motive from a single explanation. The open arm bundles capabilities:
ablate custom travel and custom projects separately before attributing a gain.

**Integration decision after live runs:** if decisions differ but the game
cannot execute the meaningful ones, extend the Living World action resolver
with a project operation and test save, copy, rewind, privacy and narration.
If choices remain repetitive despite usable actions, compare a second model on
the same traces before adding training or another inference stage.

## Long run and private notebook

Set `PILOT_TOKEN` in the process environment for authenticated endpoints.
Use `--turns 180 --repeats 1 --input-tokens 32000` for 180 individual decisions
per arm (900 requests total). Responses use JSON mode and a separate 1,024-token
generation allowance. The endpoint must accommodate both input and output.
Input includes distinct biographies, firsthand memories, relationships, local
conditions and the resident's witnessed events. A conservative UTF-8 byte budget
with room for chat framing trims oldest observations first. The ceiling is not
a padding target. Provider-reported prompt tokens appear in the trace.

In the open arm, a resident can read, write, revise or erase up to 12 private
notebook pages. Notes are self-authored and can be mistaken. Only that resident
gets the pages on subsequent turns; a notebook edit cannot itself change the
world. The notebook lasts one trajectory, not across repeats or game saves.
