import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { npcToolProfilesModuleUrl } from './npcToolProfilesModule.mjs'

function compile(file, imports = {}) {
  const { descriptor } = parse(readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8'))
  let code = ts.transpileModule(compileScript(descriptor, { id: file, inlineTemplate: true }).content, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace(/from ['"]@\/utils\/npcToolProfiles['"]/g, `from '${npcToolProfilesModuleUrl}'`)
    .replace(/from ['"]lucide-vue-next['"]/g, `from '${import.meta.resolve('lucide-vue-next')}'`)
  for (const [name, value] of Object.entries(imports)) {
    code = code.replace(new RegExp(`import ${name} from ['"][^'"]+['"];?`), value)
  }
  return `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
}
const defaults = compile('components/living-world/NpcPersonalityDefaults.vue')
const tab = (await import(compile('components/editor/LivingWorldTab.vue', {
  NpcPersonalityDefaults: `import NpcPersonalityDefaults from '${defaults}';`,
  LivingWorldAdventureButton: 'const LivingWorldAdventureButton = { render: () => null };',
}))).default
const personality = { mode: 'live', actor_ids: ['NPC'], max_active_npcs: 3, model_role: 'complex',
  workflow: 'integrated', action_tools: true, agent_steps: 1, max_output_tokens: 1200,
  max_input_chars: 48000, max_calls_per_turn: 8, memory_limit: 12 }

async function render(hostMode) {
  return renderToString(createSSRApp({ render: () => h(tab, {
    hostMode, isVn: hostMode === 'vn', busy: false, personality,
    livingWorld: { deliberation_enabled: true }, characters: [{ id: 'NPC', name: 'Lina' }],
  }) }))
}

test('adventure tab forwards RPG mode to real defaults and limits the private-decision conflict to VN', async () => {
  const combat = await render('rpg')
  assert.match(combat, /NPC combat actions/)
  assert.match(combat, /Default combat action control for new RPG sessions/)
  assert.match(combat, /RPG sessions can enable NPC authored combat abilities/)
  assert.doesNotMatch(combat, /Both systems cannot make private NPC decisions together|guide and review NPC dialogue|These features run in Visual Novel mode/)
  const vn = await render('vn')
  assert.match(vn, /NPC Personality/)
  assert.match(vn, /Default mode for new VN sessions/)
  assert.match(vn, /Both systems cannot make private NPC decisions together/)
})

const frame = compile('components/game/SessionSettingsFrame.vue', {
  '{ useDialogFocus }': 'const useDialogFocus = () => {};',
})
const settingsChildren = Object.fromEntries([
  'SessionMemorySettings', 'VnNarrationSettings', 'SessionContentSettings', 'DynamicLocationSettings',
  'StoryVisualPresets', 'LivingWorldSettings', 'SessionPortraitSettings', 'NarratorSettings',
].map(name => [name, `const ${name} = { render: () => null };`]))
const modal = (await import(compile('components/game/SessionSettingsModal.vue', {
  ...settingsChildren,
  SessionSettingsFrame: `import SessionSettingsFrame from '${frame}';`,
  ChpmSettings: "const ChpmSettings = { inheritAttrs: false, props: ['sessionId'], render() { return this.sessionId ? 'NPC_ACTION_SETTINGS' : null; } };",
}))).default

test('session modal exposes combat settings with accurate navigation while keeping dialogue-only hosts restricted', async () => {
  for (const mode of ['vn', 'rpg', 'chat', 'story', undefined]) {
    const context = {}
    await renderToString(createSSRApp({ render: () => h(modal, { mode, sessionId: 'session' }) }), context)
    const html = context.teleports?.body ?? ''
    assert.equal(html.includes('NPC_ACTION_SETTINGS'), mode === 'vn' || mode === 'rpg', String(mode))
    assert.match(html, /data-settings-tab="living_world"/)
    assert.match(html, /data-settings-tab="npc_personality"/)
    if (mode === 'rpg') {
      assert.match(html, /NPC combat actions/)
      assert.match(html, /Authored ability choices/)
      assert.doesNotMatch(html, /Decisions and private memory/)
    } else {
      assert.match(html, /NPC Personality/)
      assert.match(html, /Decisions and private memory/)
    }
  }
  const context = {}
  await renderToString(createSSRApp({ render: () => h(modal, { mode: 'rpg' }) }), context)
  assert.doesNotMatch(context.teleports?.body ?? '', /NPC_ACTION_SETTINGS/)
})
