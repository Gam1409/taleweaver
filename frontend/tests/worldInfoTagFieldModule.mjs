import { readFileSync } from 'node:fs'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
const { descriptor } = parse(readFileSync(new URL('../src/components/game/world-info/WorldInfoTagField.vue', import.meta.url), 'utf8'))
const source = compileScript(descriptor, { id: 'world-info-tags-test', inlineTemplate: true }).content
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  .replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`).replaceAll('from "vue"', `from '${import.meta.resolve('vue')}'`)
export const tagFieldModule = `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
export const TagField = (await import(tagFieldModule)).default
