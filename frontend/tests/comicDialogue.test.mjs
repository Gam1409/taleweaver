import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'

// Transpile this pure parser with the existing TypeScript dependency; no DOM or server needed.
const source = readFileSync(new URL('../src/composables/comicDialogue.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText
const { parseComicDialogue, cachedComicDialogue, knownSpeakerNames, resolveSpeakerAlias } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
)

const entities = [
  { name: 'Лина', id: 'NPC_1', image_url: '/data/lina.png' },
  { name: 'Doe, Jane', id: 'NPC_2' }
]
function parse(content) {
  return parseComicDialogue(content, {
    playerName: 'Hero',
    playerAvatar: '/hero.png',
    knownNames: knownSpeakerNames('Hero', entities),
    resolveSpeaker: name => entities.find(e => [e.name, e.id].includes(name))
  })
}

for (const prose of [
  'Одета Лина просто, но аккуратно: льняное платье приглушённого цвета.',
  'Одета Лина просто, но аккуратно: [thoughtful] "льняное платье приглушённого цвета."',
  '**Одета Лина просто, но аккуратно:** [thoughtful] "льняное платье."',
  'Лина одета просто, но аккуратно: "льняное платье."',
  'Одежда Лины: льняное платье и кожаный жилет.',
  'Her clothing: a linen dress and leather vest.',
  '服装: リネンのドレス。'
]) {
  test(`colon prose stays intact as narration: ${prose}`, () => {
    const result = parse(prose)
    assert.equal(result.dialogues.length, 1)
    assert.equal(result.dialogues[0].isNarration, true)
    assert.equal(result.narration, prose)
  })
}

for (const line of [
  'Лина: [thoughtful] "Здравствуй."',
  '[thoughtful] Лина: "Здравствуй."',
  '**Лина:** [thoughtful] "Здравствуй."'
]) {
  test(`speaker and emotion remain together: ${line}`, () => {
    const { dialogues } = parse(line)
    assert.equal(dialogues.length, 1)
    assert.equal(dialogues[0].speaker, 'Лина')
    assert.equal(dialogues[0].voiceTag, 'thoughtful')
    assert.equal(dialogues[0].text, 'Здравствуй.')
    assert.equal(dialogues[0].avatarUrl, '/data/lina.png')
    assert.equal(dialogues[0].speakerEntity.id, 'NPC_1')
    assert.ok(!dialogues[0].isNarration)
  })
}

for (const name of ['Élodie', '李', 'さくら', 'ليلى', 'O’Neill', 'Dr. Rivera']) {
  test(`quoted speech works before metadata exists: ${name}`, () => {
    const { dialogues } = parse(`${name}: «Hello.»`)
    assert.equal(dialogues.length, 1)
    assert.equal(dialogues[0].speaker, name)
    assert.equal(dialogues[0].text, 'Hello.')
    assert.ok(!dialogues[0].isNarration)
  })
}

test('known names support unquoted legacy dialogue, punctuation and metadata aliases', () => {
  assert.equal(parse('Лина: Здравствуй.').dialogues[0].speaker, 'Лина')
  assert.equal(parse('Doe, Jane: "Hello."').dialogues[0].speaker, 'Doe, Jane')
  assert.equal(parse('NPC_1: "Hello."').dialogues[0].speaker, 'Лина')
  const names = knownSpeakerNames('Hero', [], { alias: { name: 'Имя', id: 'NPC_3' } })
  assert.ok(['hero', 'you', 'alias', 'имя', 'npc_3'].every(name => names.has(name)))
})

test('player speech and directed dialogue keep identities', () => {
  const player = parse('You: "Hello."').dialogues[0]
  assert.equal(player.speaker, 'Hero')
  assert.equal(player.isPlayer, true)
  assert.equal(player.avatarUrl, '/hero.png')
  const npc = parse('Лина (to Hero): "Hello."').dialogues[0]
  assert.equal(npc.speaker, 'Лина')
  assert.equal(npc.target, 'Hero')
})

test('inline dialogue preserves narration and ordering', () => {
  const result = parse('Ветер стих. Лина: "Пойдём."\n\nДверь закрылась.\n\nHero: "Хорошо."')
  assert.deepEqual(
    result.dialogues.map(d => [d.isNarration || false, d.text]),
    [
      [true, 'Ветер стих.'],
      [false, 'Пойдём.'],
      [true, 'Дверь закрылась.'],
      [false, 'Хорошо.']
    ]
  )
})

test('a leading narration emotion remains visible in the narrator text', () => {
  const result = parse('[thoughtful] Одета Лина просто, но аккуратно: льняное платье.')
  assert.equal(result.dialogues.length, 1)
  assert.equal(result.dialogues[0].isNarration, true)
  assert.equal(result.dialogues[0].voiceTag, 'thoughtful')
  assert.equal(result.dialogues[0].text, '[thoughtful] Одета Лина просто, но аккуратно: льняное платье.')
})

test('cue-only narration, changing emotional tags and expressive pauses remain visible', () => {
  const text = '[short pause]\n[afraid] Ah…\n[relieved] Oh!\n…\n<sigh><sigh><sigh>'
  const { dialogues } = parse(text)
  assert.equal(dialogues.length, 1)
  assert.equal(dialogues[0].text, text.split('\n').join('\n\n'))
})

test('a cue-only line between speeches stays in its original position', () => {
  const { dialogues } = parse('Лина: "Oh…"\n[long pause]\nHero: "You are safe."')
  assert.deepEqual(dialogues.map(d => d.text), ['Oh…', '[long pause]', 'You are safe.'])
})

test('object labels do not become known unquoted speakers', () => {
  const knownNames = knownSpeakerNames('Hero', [{ name: 'Сундук', entity_type: 'OBJECT' }])
  const result = parseComicDialogue('Сундук: закрыт.', { knownNames, resolveSpeaker: () => null })
  assert.equal(result.dialogues[0].isNarration, true)
})


test('a unique learned alias resolves to the same NPC and ambiguous labels do not', () => {
  const mira = { id: 'mira-id', name: 'Мира', entity_type: 'NPC', metadata_json: { npc_journal: { aliases: ['Девушка', 'Искра'] } } }
  assert.equal(resolveSpeakerAlias('Искра', [mira]), mira)
  assert.equal(knownSpeakerNames('Hero', [mira]).has('искра'), true)
  const other = { id: 'other-id', name: 'Анна', entity_type: 'NPC', metadata_json: { npc_journal: { aliases: ['Девушка'] } } }
  assert.equal(resolveSpeakerAlias('Девушка', [mira, other]), null)
})

for (const [opening, closing] of [['"', '"'], ['“', '”'], ['«', '»']]) {
  test(`inner quotations keep speech together inside ${opening}${closing}`, () => {
    const speech = 'Как на ключ к ответу на вопрос «почему это произошло» и «что делать дальше». Другие — объект исследования.'
    const result = parse(`Лина: [calm] ${opening}${speech}${closing} Она сделала паузу.`)
    assert.deepEqual(result.dialogues.map(d => [d.speaker, d.text]), [
      ['Лина', speech], ['Game Master', 'Она сделала паузу.']
    ])
    assert.equal(result.dialogues[0].voiceTag, 'calm')
  })
}

test('an inner quotation at the end retains its closing delimiter', () => {
  assert.equal(parse('Лина: "Он сказал «пора»"').dialogues[0].text, 'Он сказал «пора»')
})

test('punctuation outside a quoted reply does not create an empty narrator panel', () => {
  const result = parse('Лина: [whispers] "Десять минут тишины".\n\nМики стоит у двери.')
  assert.deepEqual(result.dialogues.map(line => [!!line.isNarration, line.text]), [
    [false, 'Десять минут тишины.'], [true, 'Мики стоит у двери.'],
  ])
})

test('inline punctuation returns to the preceding speech before new narration', () => {
  const result = parse('Лина: "Тише". Мики закрыла дверь.')
  assert.deepEqual(result.dialogues.map(line => [!!line.isNarration, line.text]), [
    [false, 'Тише.'], [true, 'Мики закрыла дверь.'],
  ])
})

test('loose formatting markers never create narrator panels, but meaningful silence remains', () => {
  for (const marker of ['*', '**', '_', '•', '·']) {
    const result = parse(`Лина: "Тише."\n${marker}`)
    assert.equal(result.dialogues.length, 1)
    assert.equal(result.dialogues[0].text, 'Тише.')
  }
  for (const text of ['...', '…', '?', '!', 'В комнате тихо.']) {
    assert.equal(parse(text).dialogues[0].text, text)
  }
})


test('streaming replaces only the changed message cache without evicting settled replies', () => {
  const parser = cachedComicDialogue({ knownNames: new Set(), resolveSpeaker: () => undefined })
  const history = Array.from({ length: 300 }, () => ({}))
  const settled = history.map((message, index) => parser(`Earlier scene ${index}.`, message))
  const current = {}
  for (let token = 0; token < 400; token++) parser(`A reply ${token}`, current)
  history.forEach((message, index) => {
    assert.equal(parser(`Earlier scene ${index}.`, message), settled[index])
  })
  assert.notEqual(parser('An edited reply.', history[0]), settled[0])
  assert.equal(settled[0].narration, 'Earlier scene 0.')
  const other = cachedComicDialogue({ knownNames: new Set(), resolveSpeaker: () => undefined })
  assert.notEqual(other('Earlier scene 0.', history[0]), settled[0], 'identity changes own a fresh cache')
})
