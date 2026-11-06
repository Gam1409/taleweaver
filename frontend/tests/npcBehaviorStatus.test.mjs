import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'

const compile = code => ts.transpileModule(code, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
const dataUrl = code => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const helper = dataUrl(compile(readFileSync(new URL('../src/composables/useNpcBehaviorStatus.ts', import.meta.url), 'utf8')))
const { updateNpcBehaviorStatus } = await import(helper)
const { descriptor } = parse(readFileSync(new URL('../src/components/game/immersive/NpcBehaviorIndicator.vue', import.meta.url), 'utf8'))
const script = compileScript(descriptor, { id: 'npc-behavior-status', inlineTemplate: true }).content
const component = (await import(dataUrl(compile(script).replace(
  /from ['"]@\/composables\/useNpcBehaviorStatus['"]/g, `from '${helper}'`,
)))).default
const status = (quality = 'simplified', mode = 'live') => ({
  module_version: '1.0.0', mode, quality, reason: 'analysis_failed',
  cooldown_remaining: quality === 'simplified' ? 3 : 0,
  unreviewed_turns: 1, total_simplified_turns: 1,
})
const render = sessionId => renderToString(createSSRApp({ render: () => h(component, { sessionId }) }))

test('simplified behavior and its module version are visible outside narration', async () => {
  updateNpcBehaviorStatus('one', status())
  const html = await render('one')
  assert.match(html, /NPC Personality: simplified RP/)
  assert.match(html, /v1\.0\.0/)
  assert.match(html, /after 3 turns/)
  assert.match(html, /role="status"/)
})

test('an indicator never crosses sessions and stays hidden for standard mode', async () => {
  updateNpcBehaviorStatus('one', status())
  assert.doesNotMatch(await render('other'), /NPC Personality/)
  updateNpcBehaviorStatus('one', status('simplified', 'off'))
  assert.doesNotMatch(await render('one'), /NPC Personality/)
})

test('a verified snapshot clears simplified presentation and cooldown', async () => {
  updateNpcBehaviorStatus('one', status())
  updateNpcBehaviorStatus('one', status('verified'))
  const html = await render('one')
  assert.match(html, /NPC Personality/)
  assert.doesNotMatch(html, /simplified RP|after 3 turns/)
})

test('invalid or missing metadata clears the indicator', async () => {
  updateNpcBehaviorStatus('one', status())
  updateNpcBehaviorStatus('one', null)
  assert.doesNotMatch(await render('one'), /NPC Personality/)
})
