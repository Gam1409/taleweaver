import { readFileSync } from 'node:fs'
import ts from 'typescript'

export const sessionTransferModule = `data:text/javascript;base64,${Buffer.from(
  ts.transpileModule(readFileSync(new URL('../src/services/sessionTransfer.ts', import.meta.url), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText,
).toString('base64')}`
