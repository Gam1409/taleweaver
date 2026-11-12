import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { Buffer } from 'node:buffer'
import ts from 'typescript'
import { effectScope, nextTick, ref } from 'vue'

const compile = file => ts.transpileModule(readFileSync(new URL(file, import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const uri = text => `data:text/javascript;base64,${Buffer.from(text).toString('base64')}`
const policyUri = uri(compile('../src/utils/sessionTypography.ts'))
const { sessionTypography, proseDirection, CONTENT_LANGUAGES } = await import(policyUri)
const controller = compile('../src/composables/useSessionTypography.ts')
  .replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace("from '@/utils/sessionTypography'", `from '${policyUri}'`)
  .replace("import { loadSessionFontStyle } from '@/services/sessionFontStyles';", 'export const loads = []; const loadSessionFontStyle = font => { loads.push(font); return Promise.resolve() };')
const { useSessionTypography, loads } = await import(uri(controller))

test('persisted language names and locale aliases select the approved families', () => {
  for (const [language, family] of [
    ['', 'Alegreya Sans'], ['English', 'Alegreya Sans'], ['Russian', 'Alegreya Sans'], ['ru-RU', 'Alegreya Sans'],
    ['Arabic', 'Baloo Bhaijaan 2'], ['ar-SA', 'Baloo Bhaijaan 2'], ['Japanese', 'M PLUS Rounded 1c'], ['ja-JP', 'M PLUS Rounded 1c'],
    ['Chinese', 'Noto Sans SC'], ['zh-CN', 'Noto Sans SC'], ['zh-Hans', 'Noto Sans SC'],
    ['Traditional Chinese', 'Noto Sans TC'], ['zh-TW', 'Noto Sans TC'], ['zh_Hant_TW', 'Noto Sans TC'], ['zh-HK', 'Noto Sans TC'],
    ['zh-Hans-TW', 'Noto Sans SC'], ['zh_Hans_HK', 'Noto Sans SC'], ['zh-Hant-CN', 'Noto Sans TC'],
    ['Korean', 'Noto Sans KR'], ['ko-KR', 'Noto Sans KR']
  ]) assert.equal(sessionTypography(language).family, family, language)
  assert.equal(new Set(CONTENT_LANGUAGES.map(item => item.code)).size, CONTENT_LANGUAGES.length)
})

test('prose direction follows actual content rather than changing toolbar direction', () => {
  assert.equal(proseDirection('«أهلاً بك»'), 'rtl')
  assert.equal(proseDirection('Mira: welcome'), 'ltr')
  assert.equal(proseDirection('Прочитаем письмо?'), 'ltr')
  assert.equal(proseDirection('手紙を読みましょう'), 'ltr')
})

test('confirmed language changes update teleported UI and leaving restores the original scope', async t => {
  const attrs = new Map(), styles = new Map([['--session-font', 'Original font']])
  const root = { style: { getPropertyValue: key => styles.get(key) || '', setProperty: (key, value) => styles.set(key, value), removeProperty: key => styles.delete(key) }, getAttribute: key => attrs.get(key) ?? null, setAttribute: (key, value) => attrs.set(key, value), removeAttribute: key => attrs.delete(key) }
  const original = globalThis.document
  globalThis.document = { documentElement: root }
  t.after(() => { globalThis.document = original })
  const language = ref('Russian'), scope = effectScope()
  scope.run(() => useSessionTypography(language))
  assert.equal(attrs.get('data-session-font'), 'Alegreya Sans')
  language.value = 'Arabic'
  await nextTick()
  assert.match(styles.get('--session-font'), /Baloo Bhaijaan 2/)
  assert.equal(attrs.get('data-session-script'), 'arabic')
  assert.equal(loads.at(-1), 'baloo-bhaijaan-2')
  scope.stop()
  assert.equal(styles.get('--session-font'), 'Original font')
  assert.equal(attrs.has('data-session-font'), false)
})

test('all vendored font files match their checksums and carry redistribution licenses', () => {
  const root = new URL('../public/assets/fonts/session/', import.meta.url)
  const manifest = JSON.parse(readFileSync(new URL('sources.json', root)))
  assert.equal(manifest.families.length, 6)
  for (const family of manifest.families) {
    const directory = new URL(family.directory + '/', root)
    assert.match(readFileSync(new URL('OFL.txt', directory), 'utf8'), /SIL OPEN FONT LICENSE/i)
    const checksums = readFileSync(new URL('SHA256SUMS', directory), 'utf8').trim().split('\n')
    assert.equal(checksums.length, family.files)
    for (const line of checksums) {
      const [digest, filename] = line.split(/\s+/)
      const data = readFileSync(new URL(filename, directory))
      assert.equal(data.subarray(0, 4).toString(), 'wOF2')
      assert.equal(createHash('sha256').update(data).digest('hex'), digest)
    }
    const css = readFileSync(new URL(`../src/assets/session-fonts/${family.directory}.css`, import.meta.url), 'utf8')
    assert.doesNotMatch(css, /url\(https?:/)
    for (const [, filename] of css.matchAll(/url\(\/assets\/fonts\/session\/[^/]+\/([^)]*)\)/g)) assert.ok(existsSync(new URL(filename, directory)))
  }
})
