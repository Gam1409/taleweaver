import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'

const file = new URL('../src/components/game/DebugPlayerLocation.vue', import.meta.url)
const { descriptor } = parse(readFileSync(file, 'utf8'))
const source = compileScript(descriptor, { id: 'debug-player-location', inlineTemplate: true }).content
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replaceAll('from "vue"', `from '${import.meta.resolve('vue')}'`)
  .replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace("from 'lucide-vue-next'", `from '${import.meta.resolve('lucide-vue-next')}'`)
const { default: Component } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const render = props => renderToString(createSSRApp({ render: () => h(Component, props) }))

test('world map exposes a styled explicit player relocation control', async () => {
  const html = await render({ sceneId: 'RESEARCH_LAB', currentSceneId: 'CORRIDOR', busy: false })
  assert.match(html, /Move player here/)
  assert.match(html, /rounded-xl/)
  assert.doesNotMatch(html, /<button[^>]* disabled(?:=|>| )/)
  assert.match(html, /NPCs, inventory and story time stay unchanged/)
})

test('current, unknown and busy destinations cannot be submitted', async () => {
  for (const props of [
    { sceneId: 'LAB', currentSceneId: 'LAB', busy: false },
    { sceneId: '', currentSceneId: 'LAB', busy: false },
    { sceneId: 'LAB', currentSceneId: 'CORRIDOR', busy: true },
  ]) assert.match(await render(props), /<button[^>]* disabled(?:=|>| )/)
  assert.match(await render({ sceneId: 'LAB', currentSceneId: 'LAB', busy: false }), /Player is here/)
})
