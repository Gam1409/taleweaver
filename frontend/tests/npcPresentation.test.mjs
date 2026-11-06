import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'

const source = readFileSync(new URL('../src/utils/npcPresentation.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const { DEFAULT_PORTRAIT_PREFERENCES: off, EMOTION_PALETTE: palette, portraitStyle, emotionLabel, thoughtText, portraitPreferences, pagePortraitCues } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const on = { emotion_palette: true, character_thoughts: true, brightness: 40 }
const cue = { emotion: 'fear', intensity: 75, thought: 'I can manage.' }

test('presentation defaults off and invalid preferences cannot enable it', () => {
  assert.deepEqual(portraitPreferences(undefined), off)
  assert.deepEqual(portraitPreferences({ ...on, emotion_palette: 'true' }), off)
  assert.deepEqual(portraitPreferences({ ...on, brightness: 101 }), off)
  assert.deepEqual(portraitStyle(cue, off), {})
  assert.equal(thoughtText(cue, off), '')
})

test('all backend emotion names have a color except unknown, which has no assessment', () => {
  const backend = readFileSync(new URL('../../backend/core/npc_presentation.py', import.meta.url), 'utf8')
  const enumSource = backend.split('Emotion = Literal[')[1].split(']')[0]
  const names = [...enumSource.matchAll(/"([a-z_]+)"/g)].map(match => match[1])
  assert.deepEqual(names.filter(name => name !== 'unknown').sort(), Object.keys(palette).sort())
  assert.deepEqual(portraitStyle({ emotion: 'unknown', intensity: 80 }, on), {})
  assert.deepEqual(portraitStyle({ emotion: 'calm' }, on), {})
  assert.deepEqual(portraitStyle({ emotion: 'constructor', intensity: 80 }, on), {})
})

test('one explicit dominant emotion controls hue and intensity controls strength', () => {
  assert.equal(emotionLabel(cue, on), 'Fear · 75%')
  assert.notDeepEqual(portraitStyle({ ...cue, intensity: 10 }, on), portraitStyle(cue, on))
  assert.match(portraitStyle(cue, on).boxShadow, /12,10,18/)
  assert.deepEqual(portraitStyle(cue, { ...on, brightness: 0 }), {})
  for (const intensity of [true, '75', 101, -1, 1.5]) assert.deepEqual(portraitStyle({ ...cue, intensity }, on), {})
})

test('thoughts and emotions are independent and thoughts have a hard length limit', () => {
  assert.equal(thoughtText(cue, { ...on, emotion_palette: false }), cue.thought)
  assert.equal(thoughtText({ ...cue, thought: 'x'.repeat(161) }, on), '')
  assert.equal(thoughtText({ thought: '🌸'.repeat(160) }, on), '🌸'.repeat(160))
  assert.deepEqual(portraitStyle(cue, { ...on, emotion_palette: false }), {})
  assert.notDeepEqual(portraitStyle(cue, { ...on, character_thoughts: false }), {})
})

test('viewed page uses its latest narration and never inherits a stale emotion', () => {
  const assessed = { assistantMessage: { portrait_state: { version: 1, npcs: { RIN: cue } } } }
  assert.deepEqual(pagePortraitCues([assessed]), { RIN: cue })
  assert.deepEqual(pagePortraitCues([assessed, { assistantMessage: {} }]), {})
  assert.deepEqual(pagePortraitCues([{ assistantMessage: { portrait_state: { version: 2, npcs: { RIN: cue } } } }]), {})
  assert.deepEqual(pagePortraitCues([]), {})
})
