# Parallel requests by LLM role

Administration → Intelligence places **Allow parallel requests** next to each of
the five model connections. Enable it only for a server capable of overlapping
inference; start with the default maximum of two (range two to four). Save the LLM
settings. Provider, model, sampling, prompts and token limits remain independent.

This is permission and capacity, not an instruction to run every workflow stage
concurrently. The existing NPC Personality → **Concurrent NPC analyses** setting
is an additional session limit. The effective width is the smaller of the session
and connection limits. A session limit of one remains sequential.

## What can overlap

Independent NPC dialogue-intention analyses can overlap after their host inputs
have been prepared sequentially. They all read the same confirmed turn snapshot.
Private observer inputs remain separate. No job executes movement, transfers or
other world mutations. Only after every selected analysis succeeds are the results
merged in stable actor order, passed together to the narrator and jointly reviewed.
The existing request budget, single shared proposal retry and publication checks
remain in place. Dependent stages and canonical world updates remain sequential.

An NPC wanting to leave and another wanting to approach that NPC are proposals,
not two independently successful actions. A request depending on the result of
another action must wait for that result. CHPM currently controls dialogue
intentions; physical outcomes still belong to the host turn resolution. This
setting does not implement a general multi-agent action resolver, and a model's
joint review is not proof that every possible narrative contradiction is detected.

## Shared servers and recovery

Configured roles share one durable admission pool per effective HTTP origin,
including native cloud providers such as DeepSeek. Model names and API paths do
not create extra slots. Simultaneous participants use the smallest participating
limit. A role with parallel requests disabled is exclusive: it waits for the pool
to empty, then occupies it alone. Foreground waiting requests retain priority over
background maintenance. Existing streams and synchronous requests use the same pool.

Connection policies apply even when legacy `INFERENCE_SERIALIZATION_ENABLED` is
off. Keep that flag enabled when embeddings share the inference server: embedding
admission stays exclusive. Empty legacy role settings retain their old behavior
until the connection form is saved. Saving writes an explicit policy for every
visible role, including unchecked controls; all unchecked means one LLM request at
a time per server. Older API clients that omit the setting preserve existing
policies. Once any role is configured, unspecified roles default to exclusive admission.
Existing Living World overlap cannot create an extra lane for a configured role.
Single-worker operation is still required. Separate URL aliases or other client
applications are outside this in-process capacity accounting.

In system diagnostics, `llm.started` marks operation entry, which can precede
queue admission. Use `inference.admitted` and `inference.completed` to assess
overlap. Each `inference.queued` record includes a safe endpoint fingerprint,
the request's capacity, configured/legacy policy, and background/concurrent-lane
flags. Several started or queued operations do not prove simultaneous inference.

Every admitted request has its own durable token. Unconfirmed completion in any
slot fences the entire origin, including exclusive requests and the legacy Living
World lane. Restarting the application preserves this fence. A late confirmed
receipt clears only its own token; administrator recovery also addresses that
specific token. No timeout automatically clears another running request.

## Performance and quality

Compare **Last NPC analysis timings**, especially preparation wall time and host
queue wait, at one and two simultaneous requests. A server that serializes work
internally may gain nothing or become slower. Parallel execution does not improve
the model's reasoning by itself. It can make independent analyses more practical
without trimming their inputs or skipping validation. No live-model speed or
decision-quality benchmark is implied by the mocked regression tests.
