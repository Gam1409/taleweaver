import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import ts from 'typescript'
import { mountSfc, settle } from './mountSfc.mjs'
import { npcToolProfiles } from './npcToolProfilesModule.mjs'

const require = createRequire(import.meta.url)
const { NPC_TOOL_PROFILES, NPC_TOOL_PROFILE_REQUIREMENTS, findNpcToolProfile } = npcToolProfiles

test('one profile catalog provides the exact persisted IDs and cautious compatibility help', () => {
  assert.deepEqual(NPC_TOOL_PROFILES.map(profile => [profile.id, profile.label]), [
    ['auto', 'Auto'], ['anthropic', 'Anthropic'], ['openai', 'OpenAI'], ['mistral', 'Mistral'],
    ['gemma', 'Gemma'], ['deepseek', 'DeepSeek'], ['qwen', 'Qwen'],
  ])
  assert.equal(findNpcToolProfile().id, 'auto')
  assert.equal(findNpcToolProfile('future-profile'), undefined)
  assert.match(findNpcToolProfile('auto').help, /Preserves the existing configured/)
  for (const id of ['gemma', 'qwen']) assert.match(findNpcToolProfile(id).help, /Automatic protocol, prefers JSON compatibility/)
  assert.match(NPC_TOOL_PROFILE_REQUIREMENTS, /compatible model and server/)
  assert.match(NPC_TOOL_PROFILE_REQUIREMENTS, /Native tools also require a compatible tool-aware chat template/)
  assert.match(NPC_TOOL_PROFILE_REQUIREMENTS, /varies by model version/)
})

for (const [hostMode, workflow, notebookEnabled] of [['vn', 'integrated', true], ['rpg', 'integrated', true], ['vn', 'staged', false]]) {
  test(`${hostMode} ${workflow} notebook=${notebookEnabled} profile dropdown drives the real session GET/draft/PATCH path without changing protocol or budget`, async t => {
    const settings = {
      mode: 'live', actor_ids: ['NPC'], max_active_npcs: 1, model_role: 'complex',
      workflow, action_tools: workflow === 'integrated', agent_steps: 1, tool_protocol: workflow === 'staged' ? 'auto' : 'json',
      tool_profile: workflow === 'staged' ? 'gemma' : 'qwen', max_calls_per_turn: 25, max_input_chars: 64000,
      max_output_tokens: 1200, memory_limit: 12, notebook_enabled: notebookEnabled, semantic_memory: true,
    }
    const saved = { settings, revision: 3, host_mode: hostMode, available: true,
      characters: [{ id: 'NPC', name: 'Lina' }], usage: { status: 'idle' }, trace: [] }
    const requests = []
    const http = { apiFetch: async (_path, init) => {
      requests.push(init)
      if (init.method === 'GET') return Response.json(saved)
      const body = JSON.parse(init.body)
      assert.equal(body.expected_revision, 3)
      assert.deepEqual(body.settings, { ...settings, tool_profile: 'mistral' })
      return Response.json({ ...saved, revision: 4, settings: body.settings })
    } }
    const source = readFileSync(new URL('../src/composables/useChpmSettings.ts', import.meta.url), 'utf8')
    const code = ts.transpileModule(source, { compilerOptions: {
      target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
    } }).outputText
    const module = { exports: {} }
    new Function('require', 'module', 'exports', code)(name => name === '@/services/http' ? http : require(name), module, module.exports)
    let state
    const view = mountSfc('components/game/ChpmSettings.vue', { sessionId: 'saved-session' }, {
      '@/composables/useChpmSettings': { useChpmSettings: (...args) => { state = module.exports.useChpmSettings(...args); return state } },
      '@/utils/npcToolProfiles': npcToolProfiles,
    })
    t.after(() => view.app.unmount())
    await settle()
    assert.equal(state.dirty.value, false)
    const select = view.all().find(node => node.props.name === 'npc-tool-profile')
    assert.ok(select)
    assert.deepEqual(select.children.filter(node => node.type === 'option').map(node => node.props.value),
      NPC_TOOL_PROFILES.map(profile => profile.id))
    const minimum = state.minimumCalls.value
    select.props.onChange({ target: { value: 'mistral' } })
    await settle()
    assert.equal(state.draft.value.tool_profile, 'mistral')
    assert.equal(state.status.value.settings.tool_profile, settings.tool_profile)
    assert.equal(state.minimumCalls.value, minimum)
    assert.equal(await state.save(), true)
    assert.deepEqual(requests.map(request => request.method), ['GET', 'PATCH'])
    assert.equal(state.dirty.value, false)
    assert.equal(state.status.value.settings.tool_profile, 'mistral')
  })
}
