import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { createSSRApp, h, ref } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'
import { npcToolProfilesModuleUrl } from './npcToolProfilesModule.mjs'

const source = readFileSync(new URL('../src/components/game/ChpmSettings.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const script = compileScript(descriptor, { id: 'chpm-settings', inlineTemplate: true }).content
const compiled = ts.transpileModule(script, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
  .replace(/from ['"]@\/utils\/npcToolProfiles['"]/g, `from '${npcToolProfilesModuleUrl}'`)
  .replace(/import .* from ['"]@\/composables\/useChpmSettings['"];?/, 'const useChpmSettings = () => globalThis.__chpmSettingsFixture;')
const component = (await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)).default

async function render(count, warnings = [], statusFields = {}, draftFields = {}) {
  globalThis.__chpmSettingsFixture = {
    status: ref({ available: true, characters: [], usage: { status: 'idle' }, trace: [], ...statusFields }),
    draft: ref({ mode: 'live', actor_ids: Array.from({ length: count }, (_, i) => `${i}`), max_calls_per_turn: 8, ...draftFields }),
    busy: ref(false), error: ref(''), minimumCalls: ref(count + 5),
    budgetWarning: ref(false), historyWarnings: ref(warnings),
    load() {}, save() {}, selectStandard() {}, setNotebookEnabled() {},
  }
  try {
    return await renderToString(createSSRApp({ render: () => h(component, { sessionId: 'session' }) }))
  } finally {
    delete globalThis.__chpmSettingsFixture
  }
}

test('multiple NPCs disclose waiting and the repair reserve, without a made-up ETA', async () => {
  const html = await render(3)
  assert.match(html, /processed sequentially/)
  assert.match(html, /does not stream/)
  assert.match(html, /Minimum for this selection: 8/)
  assert.match(html, /Later card edits do not replace/)
  assert.doesNotMatch(await render(1), /processed sequentially/)
})

test('private notebook help explains opt-in tool costs and latest-only restore behavior', async () => {
  const html = await render(1, [], {}, { notebook_enabled: true, agent_steps: 1 })
  assert.match(html, /Private NPC notebooks/)
  assert.match(html, /16,000,000 UTF-8 bytes/)
  assert.match(html, /Notes may be mistaken and are not world facts/)
  assert.match(html, /Undo or Chronicles restore/)
  assert.match(html, /no notebook history is kept/)
  assert.match(html, /<option value="0" disabled>/)
  assert.match(html, /up to two local tool operations/)
  assert.doesNotMatch(html, /read-only lookups/)
  assert.doesNotMatch(await render(1, [], {}, { mode: 'shadow' }), /Private NPC notebooks/)
})

test('notebook compatibility is selectable without changing the tool round limit', async () => {
  const html = await render(1, [], {}, { notebook_enabled: true, agent_steps: 2, tool_protocol: 'json' })
  assert.match(html, /Memory tool compatibility/)
  assert.match(html, /<select name="npc-memory-tool-protocol" value="json"[^>]*>/)
  assert.match(html, /same private notebook, limits and request budget/)
  assert.doesNotMatch(await render(1, [], {}, { notebook_enabled: false }), /Memory tool compatibility/)
})

test('session tool profile catalog is separate from protocol and explains compatibility requirements', async () => {
  const html = await render(1, [], {}, { workflow: 'integrated', tool_protocol: 'json', tool_profile: 'qwen' })
  assert.match(html, /Tool-calling profile/)
  const profile = html.match(/<select name="npc-tool-profile"[\s\S]*?<\/select>/)?.[0] ?? ''
  assert.match(profile, /value="qwen"/)
  assert.deepEqual([...profile.matchAll(/<option value="([^"]+)"/g)].map(match => match[1]),
    ['auto', 'anthropic', 'openai', 'mistral', 'gemma', 'deepseek', 'qwen'])
  assert.match(html, /name="npc-memory-tool-protocol" value="json"/)
  assert.match(html, /Automatic protocol, prefers JSON compatibility/)
  assert.match(html, /Automatic considers the selected profile and provider support/)
  assert.match(html, /compatible model and server/)
  assert.match(html, /Native tools also require a compatible tool-aware chat template/)
  assert.match(html, /Support varies by model version/)
  assert.doesNotMatch(await render(1, [], {}, { mode: 'off', tool_profile: 'qwen' }), /npc-tool-profile/)
})

test('session tools offer a third recovery round and explain its cast budget', async () => {
  const html = await render(3, [], {}, { notebook_enabled: true, agent_steps: 3 })
  assert.match(html, /<select name="npc-agent-tool-rounds"[^>]*>[\s\S]*?<option value="3">Up to 3 rounds/)
  assert.match(html, /correct an error and check the result/)
  assert.match(html, /5 for three rounds/)
})

test('world actions are off by default and expose compatible controls only in enabled mode', async () => {
  const initial = await render(1, [], {}, { workflow: 'staged', notebook_enabled: false })
  const unchecked = initial.match(/<input[^>]*name="npc-world-actions"[^>]*>/)?.[0]
  assert.ok(unchecked)
  assert.doesNotMatch(unchecked, /checked/)
  const enabled = await render(1, [], {}, { action_tools: true, workflow: 'integrated', notebook_enabled: false, agent_steps: 1 })
  assert.match(enabled.match(/<input[^>]*name="npc-world-actions"[^>]*>/)?.[0] ?? '', /checked/)
  assert.match(enabled, /NPC world actions \(experimental\)/)
  assert.match(enabled, /engine validates changes to the world/)
  assert.match(enabled, /player.*choices stay theirs/)
  assert.match(enabled, /Agent tool compatibility/)
  assert.match(enabled, /<option value="0" disabled>/)
  assert.doesNotMatch(await render(1, [], {}, { mode: 'shadow', action_tools: true }), /npc-world-actions/)
})

test('RPG settings offer combat actions without implying VN dialogue or private memory support', async () => {
  const html = await render(2, [], { host_mode: 'rpg', agenda_counts: { active: 2, closed: 1 }, agenda: [{}], trace: [{}] }, {
    mode: 'live', control_scope: 'combat_actions', action_tools: true, workflow: 'integrated', agent_steps: 2,
    notebook_enabled: true, semantic_memory: true,
  })
  assert.match(html, /NPC combat actions/)
  assert.match(html, /authored abilities on their own combat turn/)
  assert.match(html, /player.*choices stay theirs/)
  assert.match(html, /Combat action control \(experimental\)/)
  assert.match(html, /name="npc-world-actions"[^>]*checked/)
  assert.match(html, /name="npc-agent-tool-rounds"/)
  assert.match(html, /name="npc-memory-tool-protocol"/)
  assert.match(html, /Complex model/)
  assert.match(html, /Requests per turn/)
  assert.match(html, /<option value="staged" disabled>/)
  assert.match(html, /psychological memory are available only in VN sessions/)
  assert.doesNotMatch(html, /value="shadow"|control-scope|Private NPC notebooks|Semantic NPC memory|Remembered observations|Recorded agenda|Administrator decision trace|Concurrent NPC analyses|validate dialogue|narration repair/)
})

test('RPG off mode keeps a standard option and enabled action opt-in is explicit', async () => {
  const disabled = await render(1, [], { host_mode: 'rpg' }, { mode: 'off' })
  assert.match(disabled, /value="off"/)
  assert.doesNotMatch(disabled, /name="npc-world-actions"|value="shadow"/)
  const pending = await render(1, [], { host_mode: 'rpg' }, { workflow: 'staged', action_tools: false })
  assert.match(pending, /Enable combat action control before saving/)
  assert.doesNotMatch(pending.match(/<input[^>]*name="npc-world-actions"[^>]*>/)?.[0] ?? '', /checked/)
})

test('a localized proposal failure names only the paused NPC and escapes its detail', async () => {
  const html = await render(2, [], {
    characters: [{ id: 'LINA', name: 'Lina' }, { id: 'MILA', name: 'Mila' }],
    usage: { status: 'validated', actor_failures: { LINA: '<script>invalid quote</script>' } },
  })
  assert.match(html, /Paused this turn: Lina/)
  assert.match(html, /&lt;script&gt;invalid quote&lt;\/script&gt;/)
  assert.doesNotMatch(html, /Paused this turn: Mila|<script>/)
})

test('parallel analysis is an explicit saved setting with unchanged request limits', async () => {
  const html = await render(3, [], {}, { npc_concurrency: 2 })
  assert.match(html, /up to 2 NPCs at once/)
  assert.doesNotMatch(html, /processed sequentially/)
  assert.match(html, /shared request budget stay the same/)
  assert.match(html, /Changes apply after Save/)
  assert.match(html, /failed turns can spend more/)
})

test('saved timings distinguish unknown input processing from a measured zero queue', async () => {
  const html = await render(2, [], { usage: { status: 'validated', preparation_ms: 2000, timings: [{
    actor_id: '<script>NPC</script>', phase: 'proposal', duration_ms: 1000, queue_ms: 0,
    ttft_ms: null, prefill_ms: null, server_generation_ms: 500, cached_prompt_tokens: 42,
  }] } })
  assert.match(html, /Last NPC analysis timings/)
  assert.match(html, /2\.000 s/)
  assert.match(html, /0\.000 s/)
  assert.match(html, /0\.500 s/)
  assert.match(html, /Unavailable/)
  assert.match(html, /&lt;script&gt;NPC/)
  assert.doesNotMatch(html, /<script>/)
})

test('timings retain the recorded workflow when another workflow is selected', async () => {
  const timing = { phase: 'proposal', duration_ms: 1000 }
  const html = await render(1, [], { usage: { workflow: 'staged', calls: 3, timings: [timing] } }, { workflow: 'integrated' })
  assert.match(html, /Workflow used: Staged tools, then decision/)
  assert.doesNotMatch(html, /Workflow used: Integrated/)
  const legacy = await render(1, [], { usage: { calls: 3, timings: [timing] } }, { workflow: 'integrated' })
  assert.match(legacy, /Not recorded for this result/)
})

test('large casts expose focused processing and an explicit all-present choice', async () => {
  const html = await render(20)
  assert.match(html, /Character roster \(up to 20/)
  assert.match(html, /Active NPCs per turn/)
  assert.match(html, /Twenty active NPCs require 25 NPC Personality requests/)
  assert.match(html, /Attribution is model-based and can be mistaken/)
})

test('cooldown shows the earlier rejection separately and escapes its validation text', async () => {
  const html = await render(2, [], {
    usage: { status: 'failed', simplified: true, calls: 0, input_chars: 0, output_chars: 0 },
    last_proposal_failure: {
      source: 'previous_turn_snapshot', reason: 'analysis_failed', reply_id: 'reply',
      proposal_feedback: ['candidates.refuse.preconditions: Field required', '<script>not markup</script>'],
    },
  })
  assert.match(html, /Most recent rejected NPC proposal/)
  assert.match(html, /candidates.refuse.preconditions: Field required/)
  assert.match(html, /earlier failed turn/)
  assert.match(html, /previous turn snapshot/)
  assert.match(html, /&lt;script&gt;/)
  assert.doesNotMatch(html, /<script>/)
})

test('an input-budget failure stays visible without proposal feedback', async () => {
  const html = await render(2, [], {
    usage: { status: 'failed', simplified: true, calls: 0, input_chars: 0, output_chars: 0 },
    last_analysis_failure: {
      source: 'recent_turn', reason: 'analysis_failed', reply_id: 'reply', proposal_feedback: [],
      detail: 'CHPM required context exceeds its budget (26800 > 21952 characters).',
    },
  })
  assert.match(html, /Most recent failed NPC analysis/)
  assert.match(html, /26800 &gt; 21952/)
  assert.doesNotMatch(html, /Most recent rejected NPC proposal/)
  assert.match(html, /separate from output tokens and the model&#39;s context window/)
})

test('saved selections outside the known list remain visible for explicit removal', async () => {
  const html = await render(1)
  assert.match(html, /Changing limits keeps them selected/)
  assert.match(html, /Saved selection: 0/)
  assert.doesNotMatch(html, /PRIVATE_UNKNOWN_NAME/)
})

test('capacity warning exposes the explicit standard-mode choice and preserved history', async () => {
  const html = await render(1, [{ id: 'npc', name: 'Lina', status: 'pause_required', used: { events: 8180, beliefs: 20 }, limits: { events: 8192, beliefs: 2048 }, active_events: 244, archived_events: 7936 }])
  assert.match(html, /Needs attention/)
  assert.match(html, /8180\/8192 events/)
  assert.match(html, /244 active \/ 7936 archived events/)
  assert.match(html, /total storage is finite/)
  assert.match(html, /Select Standard \(save to apply\)/)
  assert.match(html, /Original identity and psychological history stay saved/)
})
