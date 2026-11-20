import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRenderer, h, nextTick, ref } from 'vue'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { npcToolProfilesModuleUrl } from './npcToolProfilesModule.mjs'

const { descriptor } = parse(readFileSync(new URL('../src/components/living-world/NpcPersonalityDefaults.vue', import.meta.url), 'utf8'))
const compiled = ts.transpileModule(compileScript(descriptor, { id: 'npc-personality-defaults', inlineTemplate: true }).content, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
  .replace(/from ['"]@\/utils\/npcToolProfiles['"]/g, `from '${npcToolProfilesModuleUrl}'`)
const component = (await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)).default
const descendants = node => [node, ...(node.children ?? []).flatMap(descendants)]
const text = node => [node.text ?? '', ...(node.children ?? []).map(text)].join('')
const settings = () => ({ mode: 'live', actor_ids: ['NPC'], max_active_npcs: 3, model_role: 'complex', max_output_tokens: 1200, max_input_chars: 24000, max_calls_per_turn: 8, memory_limit: 12, agent_steps: 0 })

function fixture(t, initial = settings(), props = {}) {
  const value = ref(initial), changes = [], root = { children: [] }
  const renderer = createRenderer({
    createElement: tag => ({ tag, props: {}, children: [] }),
    createText: value => ({ text: value }), createComment: () => ({}),
    setText: (node, value) => { node.text = value },
    setElementText: (node, value) => { node.text = value; node.children = [] },
    patchProp: (node, key, _previous, next) => { node.props[key] = next },
    insert(node, parent, anchor) {
      if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
      node.parent = parent
      const index = parent.children.indexOf(anchor)
      parent.children.splice(index < 0 ? parent.children.length : index, 0, node)
    },
    remove(node) { node.parent.children.splice(node.parent.children.indexOf(node), 1) },
    parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
  })
  const app = renderer.createApp({ render: () => h(component, {
    modelValue: value.value, characters: [{ id: 'NPC', name: 'Lina' }], ...props,
    'onUpdate:modelValue': next => { changes.push(next); value.value = next },
  }) })
  app.mount(root)
  t.after(() => app.unmount())
  const checkbox = () => descendants(root).find(node => node.props?.name === 'npc-private-notebooks')
  return { value, changes, root, checkbox }
}

test('template tool profiles offer seven choices, emit only explicit changes and preserve other preferences', async t => {
  const original = { ...settings(), workflow: 'integrated', tool_protocol: 'native',
    notebook_enabled: true, semantic_memory: true, agent_steps: 3, max_input_chars: 64000,
    max_calls_per_turn: 25, future_preference: 'retained' }
  const f = fixture(t, original)
  const select = () => descendants(f.root).find(node => node.props?.name === 'npc-tool-profile')
  assert.equal(select()?.props.value, 'auto')
  assert.deepEqual(select().children.filter(node => node.tag === 'option').map(node => node.props.value),
    ['auto', 'anthropic', 'openai', 'mistral', 'gemma', 'deepseek', 'qwen'])
  assert.equal(f.changes.length, 0)
  for (const profile of ['auto', 'anthropic', 'openai', 'mistral', 'gemma', 'deepseek', 'qwen']) {
    select().props.onChange({ target: { value: profile } })
    await nextTick()
    assert.deepEqual(f.value.value, { ...original, tool_profile: profile })
    assert.notEqual(f.value.value.actor_ids, original.actor_ids)
  }
  assert.equal(f.changes.length, 7)
  assert.equal(original.tool_profile, undefined)
})

test('template notebook opt-in emits one draft update with an agent round and unchanged budget', async t => {
  const original = settings(), f = fixture(t, original)
  assert.equal(f.checkbox()?.props.checked, false)
  f.checkbox().props.onChange({ target: { checked: true } })
  await nextTick()
  assert.equal(f.changes.length, 1)
  assert.equal(f.value.value.notebook_enabled, true)
  assert.equal(f.value.value.agent_steps, 1)
  assert.equal(f.value.value.max_calls_per_turn, 8)
  assert.equal(original.notebook_enabled, undefined)
  assert.notEqual(f.value.value.actor_ids, original.actor_ids)
  assert.match(text(f.root), /16,000,000 UTF-8 bytes/)
  assert.match(text(f.root), /Undo or Chronicles restore/)
  assert.doesNotMatch(text(f.root), /Read-only agent rounds/)
})

test('template staged lookup-only tools expose the saved profile and change only its explicit preference', async t => {
  const original = { ...settings(), workflow: 'staged', notebook_enabled: false,
    action_tools: false, agent_steps: 1, tool_profile: 'gemma', tool_protocol: 'auto' }
  const f = fixture(t, original)
  const profile = descendants(f.root).find(node => node.props?.name === 'npc-tool-profile')
  assert.ok(profile)
  assert.equal(profile.props.value, 'gemma')
  assert.equal(f.changes.length, 0)
  profile.props.onChange({ target: { value: 'qwen' } })
  await nextTick()
  assert.equal(f.changes.length, 1)
  assert.deepEqual(f.value.value, { ...original, tool_profile: 'qwen' })
  assert.equal(original.tool_profile, 'gemma')
})

test('template notebook controls retain two agent rounds and keep the off option unavailable', async t => {
  const f = fixture(t, { ...settings(), agent_steps: 2 })
  f.checkbox().props.onChange({ target: { checked: true } })
  await nextTick()
  assert.equal(f.value.value.agent_steps, 2)
  const rounds = descendants(f.root).find(node => node.props?.name === 'npc-agent-tool-rounds')
  const off = rounds.children.find(node => node.props?.value === 0)
  assert.equal(off.props.disabled, true)
  f.checkbox().props.onChange({ target: { checked: false } })
  await nextTick()
  assert.equal(f.value.value.notebook_enabled, false)
  assert.equal(f.value.value.agent_steps, 2)
})

test('template tool compatibility changes preserve private notebook choice and request limits', async t => {
  const f = fixture(t, { ...settings(), notebook_enabled: true, agent_steps: 2, tool_protocol: 'auto' })
  const protocol = descendants(f.root).find(node => node.props?.name === 'npc-memory-tool-protocol')
  protocol.props.onChange({ target: { value: 'json' } })
  await nextTick()
  assert.equal(f.value.value.tool_protocol, 'json')
  assert.equal(f.value.value.notebook_enabled, true)
  assert.equal(f.value.value.agent_steps, 2)
  assert.equal(f.value.value.max_calls_per_turn, 8)
})

test('new adventure defaults leave notebooks and tool rounds off', async t => {
  const f = fixture(t, null)
  assert.equal(f.checkbox(), undefined)
  descendants(f.root).find(node => node.tag === 'select').props.onChange({ target: { value: 'live' } })
  await nextTick()
  assert.equal(f.value.value.notebook_enabled, false)
  assert.equal(f.value.value.action_tools, false)
  assert.equal(f.value.value.agent_steps, 0)
  assert.equal(f.value.value.tool_profile, 'auto')
  assert.equal(f.checkbox().props.checked, false)
})

test('template defaults can select three rounds with the matching request reserve', async t => {
  const f = fixture(t)
  const rounds = descendants(f.root).find(node => node.props?.name === 'npc-agent-tool-rounds')
  assert.ok(rounds.children.some(node => node.props?.value === 3))
  rounds.props.onChange({ target: { value: '3' } })
  await nextTick()
  assert.equal(f.value.value.agent_steps, 3)
  assert.equal(f.value.value.max_calls_per_turn, 8)
  assert.match(text(f.root), /Minimum request budget: 9,/)
})

test('template world actions emit one draft update with compatible tools and preserve existing options', async t => {
  const original = { ...settings(), notebook_enabled: true, agent_steps: 2, max_input_chars: 64000 }
  const f = fixture(t, original)
  const checkbox = () => descendants(f.root).find(node => node.props?.name === 'npc-world-actions')
  assert.equal(checkbox().props.checked, false)
  checkbox().props.onChange({ target: { checked: true } })
  await nextTick()
  assert.equal(f.changes.length, 1)
  assert.equal(f.value.value.action_tools, true)
  assert.equal(f.value.value.workflow, 'integrated')
  assert.equal(f.value.value.agent_steps, 2)
  assert.equal(f.value.value.max_input_chars, 64000)
  assert.equal(f.value.value.max_calls_per_turn, 8)
  assert.equal(f.value.value.notebook_enabled, true)
  assert.equal(original.action_tools, undefined)
  assert.notEqual(f.value.value.actor_ids, original.actor_ids)
  assert.match(text(f.root), /player.*choices/i)
})

test('template world actions select a round and prevent Off until disabled', async t => {
  const f = fixture(t)
  const checkbox = descendants(f.root).find(node => node.props?.name === 'npc-world-actions')
  checkbox.props.onChange({ target: { checked: true } })
  await nextTick()
  assert.equal(f.value.value.agent_steps, 1)
  assert.equal(f.value.value.max_input_chars, 48000)
  const rounds = () => descendants(f.root).find(node => node.props?.name === 'npc-agent-tool-rounds')
  assert.equal(rounds().children.find(node => node.props?.value === 0).props.disabled, true)
  checkbox.props.onChange({ target: { checked: false } })
  await nextTick()
  assert.equal(f.value.value.action_tools, false)
  assert.equal(f.value.value.agent_steps, 1)
  assert.equal(rounds().children.find(node => node.props?.value === 0).props.disabled, false)
})

test('template staged workflow disables world actions while retaining notes and rounds', async t => {
  const f = fixture(t, { ...settings(), action_tools: true, workflow: 'integrated', notebook_enabled: true, agent_steps: 3 })
  const workflow = descendants(f.root).find(node => node.props?.name === 'npc-decision-workflow')
  workflow.props.onChange({ target: { value: 'staged' } })
  await nextTick()
  assert.equal(f.value.value.action_tools, false)
  assert.equal(f.value.value.notebook_enabled, true)
  assert.equal(f.value.value.agent_steps, 3)
})

test('RPG defaults expose authored combat actions and compatible controls without VN-only features', async t => {
  const f = fixture(t, { ...settings(), notebook_enabled: true, semantic_memory: true }, { hostMode: 'rpg' })
  assert.match(text(f.root), /NPC combat actions/)
  assert.match(text(f.root), /authored abilities on their own combat turn/)
  assert.match(text(f.root), /psychological memory are available only in VN sessions/)
  assert.doesNotMatch(text(f.root), /private notes|Private NPC notebooks|Semantic NPC memory|guide and review NPC dialogue|Remembered quotations|Observe/)
  assert.equal(f.checkbox(), undefined)
  const all = () => descendants(f.root)
  assert.equal(all().some(node => node.tag === 'option' && node.props?.value === 'shadow'), false)
  const workflow = all().find(node => node.props?.name === 'npc-decision-workflow')
  assert.equal(workflow.children.find(node => node.props?.value === 'staged').props.disabled, true)
  all().find(node => node.props?.name === 'npc-world-actions').props.onChange({ target: { checked: true } })
  await nextTick()
  assert.equal(f.value.value.action_tools, true)
  assert.equal(f.value.value.workflow, 'integrated')
  assert.equal(f.value.value.agent_steps, 1)
  assert.equal(f.value.value.max_input_chars, 48000)
  assert.equal(f.value.value.control_scope, undefined)
  assert.match(text(f.root), /Agent tool compatibility/)
  assert.match(text(f.root), /Minimum request budget: 3,/)
  assert.doesNotMatch(text(f.root), /repair reserve/)
})

test('RPG defaults reserve up to three initiative turns without increasing the saved budget', async t => {
  const f = fixture(t, { ...settings(), actor_ids: Array.from({ length: 9 }, (_, index) => `NPC-${index}`),
    max_active_npcs: 8, action_tools: true, workflow: 'integrated', agent_steps: 1, max_calls_per_turn: 25 }, { hostMode: 'rpg' })
  assert.match(text(f.root), /Minimum request budget: 24,/)
  const rounds = descendants(f.root).find(node => node.props?.name === 'npc-agent-tool-rounds')
  rounds.props.onChange({ target: { value: '2' } })
  await nextTick()
  assert.match(text(f.root), /Minimum request budget: 48,/)
  assert.equal(f.value.value.max_calls_per_turn, 25)
})

test('two-phase decisions are opt-in for VN actions and clear when those actions are disabled', async t => {
  const original = { ...settings(), action_tools: true, workflow: 'integrated', agent_steps: 1 }
  const f = fixture(t, original, { hostMode: 'vn' })
  const field = name => descendants(f.root).find(node => node.props?.name === name)
  assert.equal(field('npc-decision-mode')?.props.value, 'legacy')
  field('npc-decision-mode').props.onChange({ target: { value: 'two_phase' } })
  await nextTick()
  assert.equal(f.value.value.npc_decision_mode, 'two_phase')
  assert.equal(f.value.value.max_calls_per_turn, original.max_calls_per_turn)
  field('npc-world-actions').props.onChange({ target: { checked: false } })
  await nextTick()
  assert.equal(field('npc-decision-mode'), undefined)
  assert.equal(f.value.value.npc_decision_mode ?? 'legacy', 'legacy')
  const combat = fixture(t, original, { hostMode: 'rpg' })
  assert.equal(descendants(combat.root).some(node => node.props?.name === 'npc-decision-mode'), false)
})

test('decision detail can change independently of workflow and tool rounds', async t => {
  const f = fixture(t, settings(), { hostMode: 'vn' })
  const field = () => descendants(f.root).find(node => node.props?.name === 'npc-decision-detail')
  assert.equal(field().props.value, 'full')
  field().props.onChange({ target: { value: 'compact' } })
  await nextTick()
  assert.equal(f.value.value.decision_detail, 'compact')
  assert.equal(f.value.value.workflow, settings().workflow)
  assert.equal(f.value.value.agent_steps, settings().agent_steps)
})
