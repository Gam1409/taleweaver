import { readFileSync } from 'node:fs'
import ts from 'typescript'
const compile = path => ts.transpileModule(readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const uri = code => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
export async function voiceInputModule(transcribe) {
  const key = `voice-${crypto.randomUUID()}`
  globalThis[key] = transcribe
  const api = `${uri('export const api = { transcribeAudio: (...args) => globalThis[new URL(import.meta.url).hash.slice(1)](...args) }')}#${key}`
  const source = compile('composables/useVoiceInput.ts')
    .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace("import('@/composables/useApi')", `import('${api}')`)
  const module = await import(uri(source))
  return { ...module, dispose: () => { delete globalThis[key] } }
}
