import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import ts from 'typescript'

test('World forwards confirmed preferences and save from Plot to the editor', async () => {
  const source = readFileSync(new URL('../src/components/editor/WorldTab.vue', import.meta.url), 'utf8')
  // Compile the real event bindings; omit unrelated world controls.
  const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
    .replace(/import PlotTab from [^\n]+/, `const PlotTab = {
      emits: ['update:nsfw-enabled', 'update:nsfw-level', 'save-changes'],
      setup(_props, { emit }) {
        emit('update:nsfw-enabled', true)
        emit('update:nsfw-level', 'medium')
        emit('save-changes')
        return () => null
      }
    }`)
    .replace(/import \{ Save, X \} from [^\n]+/, '')
  const binding = source.match(/<PlotTab[\s\S]*?\/>/)[0]
  const { descriptor } = parse(`<script setup lang="ts">${script}</script><template>${binding}</template>`)
  const compiled = compileScript(descriptor, { id: 'editor-events', inlineTemplate: true })
  const code = ts.transpileModule(compiled.content, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
  }).outputText.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
  const { default: World } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
  const updates = []
  await renderToString(createSSRApp({ render: () => h(World, {
    form: {}, adventure: {}, debugData: {}, editingField: null, tempValue: '',
    isSaving: false, isBatchGenerating: {}, isQuickGenerating: {}, isGeneratingField: {},
    activeMenuId: null, fixNewlines: text => text,
    'onUpdate:nsfw-enabled': value => updates.push(['enabled', value]),
    'onUpdate:nsfw-level': value => updates.push(['level', value]),
    onSaveChanges: () => updates.push(['save'])
  }) }))
  assert.deepEqual(updates, [['enabled', true], ['level', 'medium'], ['save']])
})
