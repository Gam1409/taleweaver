import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(new URL('../src/utils/npcToolProfiles.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText
export const npcToolProfilesModuleUrl = `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
export const npcToolProfiles = await import(npcToolProfilesModuleUrl)
