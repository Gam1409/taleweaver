import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'

const compile = path =>
  ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
  }).outputText
const uri = code => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
export const httpModule = uri(
  compile('../src/services/http.ts').replace(
    /import .* from '@\/store\/auth';/,
    "const authState = {token:'test-token'};"
  )
)
export const sessionSnapshotModule = uri(
  compile('../src/services/sessionSnapshot.ts').replace("from './http'", `from '${httpModule}'`)
)
