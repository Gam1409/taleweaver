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

test('legacy palette remains available and unknown has no assessment', () => {
  assert.ok(Object.keys(palette).length >= 20)
  assert.equal(palette.fear.rgb, '12,10,18')
  assert.deepEqual(portraitStyle({ emotion: 'unknown', intensity: 80 }, on), {})
  assert.deepEqual(portraitStyle({ emotion: 'calm' }, on), {})
})

test('one explicit dominant emotion controls hue and intensity controls strength', () => {
  assert.equal(emotionLabel(cue, on), 'Fear · 75%')
  assert.notDeepEqual(portraitStyle({ ...cue, intensity: 10 }, on), portraitStyle(cue, on))
  assert.match(portraitStyle(cue, on).boxShadow, /12,10,18/)
  assert.deepEqual(portraitStyle(cue, { ...on, brightness: 0 }), {})
  for (const intensity of [true, '75', 101, -1, 1.5]) assert.deepEqual(portraitStyle({ ...cue, intensity }, on), {})
})

test('freeform feelings use numeric narrator colors and never borrow another feeling', () => {
  const vulnerable = { emotion: 'vulnerability', intensity: 65, color_rgb: [140, 160, 210], thought: 'I would appreciate reassurance.' }
  assert.equal(emotionLabel(vulnerable, on), 'vulnerability · 65%')
  assert.match(portraitStyle(vulnerable, on).boxShadow, /140,160,210/)
  assert.match(portraitStyle({ ...vulnerable, emotion: 'fear' }, on).boxShadow, /140,160,210/)
  assert.deepEqual(portraitStyle(vulnerable, off), {})
  assert.deepEqual(portraitStyle(vulnerable, { ...on, brightness: 0 }), {})
  assert.equal(emotionLabel({ ...vulnerable, emotion: 'Смятение' }, on), 'Смятение · 65%')
  assert.equal(thoughtText(vulnerable, { ...on, emotion_palette: false }), vulnerable.thought)
  const assessed = { assistantMessage: { portrait_state: { version: 1, npcs: { KEEPER: vulnerable } } } }
  assert.deepEqual(pagePortraitCues([assessed, { assistantMessage: {} }]), {})
  assert.deepEqual(pagePortraitCues([]), {})
})

test('uncolored labels use a fixed safe theme fallback while legacy hues remain stable', () => {
  const custom = { emotion: 'mixed relief and worry', intensity: 60 }
  assert.equal(emotionLabel(custom, on), 'mixed relief and worry · 60%')
  const fallback = portraitStyle(custom, on)
  assert.notDeepEqual(fallback, {})
  assert.deepEqual(portraitStyle({ ...custom, emotion: 'another feeling' }, on), fallback)
  assert.deepEqual(portraitStyle({ ...custom, emotion: 'constructor' }, on), fallback)
  for (const invalid of ['red', 'var(--danger)', [-1, 0, 0], [0, 256, 0], [true, 0, 0], [1.5, 0, 0], ['1', 0, 0], [0, 0], [0, 0, 0, 0], {}, []]) {
    assert.deepEqual(portraitStyle({ ...custom, color_rgb: invalid }, on), fallback)
    assert.match(portraitStyle({ emotion: 'fear', intensity: 60, color_rgb: invalid }, on).boxShadow, /12,10,18/)
  }
  for (const emotion of ['', ' ', 1, true, ['joy'], 'x'.repeat(81)]) {
    assert.deepEqual(portraitStyle({ ...custom, emotion }, on), {})
  }
  assert.equal(emotionLabel({ ...custom, emotion: '🌤'.repeat(80) }, on), '🌤'.repeat(80) + ' · 60%')
  assert.deepEqual(portraitStyle({ ...custom, intensity: 0, color_rgb: [255, 0, 0] }, on), {})
  assert.deepEqual(portraitStyle({ emotion: 'unknown', intensity: 80, color_rgb: [255, 0, 0] }, on), {})
  const markupLabel = { emotion: '<img src=x onerror=alert(1)>', intensity: 60, color_rgb: [12, 34, 56] }
  assert.equal(emotionLabel(markupLabel, on), markupLabel.emotion + ' · 60%')
  assert.match(portraitStyle(markupLabel, on).boxShadow, /12,34,56/)
  assert.doesNotMatch(JSON.stringify(portraitStyle(markupLabel, on)), /img|alert|onerror/)
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
