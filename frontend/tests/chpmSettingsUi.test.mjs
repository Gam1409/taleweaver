import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { createSSRApp, h, ref } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'

const source = readFileSync(new URL('../src/components/game/ChpmSettings.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const script = compileScript(descriptor, { id: 'chpm-settings', inlineTemplate: true }).content
const compiled = ts.transpileModule(script, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
  .replace(/import .* from ['"]@\/composables\/useChpmSettings['"];?/, 'const useChpmSettings = () => globalThis.__chpmSettingsFixture;')
const component = (await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)).default

async function render(count, warnings = []) {
  globalThis.__chpmSettingsFixture = {
    status: ref({ available: true, characters: [], usage: { status: 'idle' }, trace: [] }),
    draft: ref({ mode: 'live', actor_ids: Array.from({ length: count }, (_, i) => `${i}`), max_calls_per_turn: 8 }),
    busy: ref(false), error: ref(''), minimumCalls: ref(count + 5),
    budgetWarning: ref(false), historyWarnings: ref(warnings),
    load() {}, save() {}, selectStandard() {},
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

test('large casts expose focused processing and an explicit all-present choice', async () => {
  const html = await render(20)
  assert.match(html, /Character roster \(up to 20/)
  assert.match(html, /Active NPCs per turn/)
  assert.match(html, /Twenty active NPCs require 25 NPC Personality requests/)
  assert.match(html, /Attribution is model-based and can be mistaken/)
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
