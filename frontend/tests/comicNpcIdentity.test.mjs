import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {effectScope, ref} from 'vue'
import ts from 'typescript'

const compile = path => ts.transpileModule(readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8'),
  {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
const uri = code => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const dialogue = uri(compile('composables/comicDialogue.ts'))
const pages = uri(compile('composables/comicPages.ts'))
const identity = uri(compile('utils/npcIdentity.ts'))
const storyMessages = uri(compile('utils/storyMessages.ts'))
const turns = compile('composables/useComicTurns.ts')
  .replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace("from 'dompurify'", `from '${import.meta.resolve('dompurify')}'`)
  .replaceAll("'./comicDialogue'", JSON.stringify(dialogue))
  .replaceAll("'./comicPages'", JSON.stringify(pages))
  .replaceAll("'@/utils/npcIdentity'", JSON.stringify(identity))
  .replaceAll("'@/utils/storyMessages'", JSON.stringify(storyMessages))
const {resolveNpc, resolveNpcMetadata, parseAssistantContent, useComicTurns} = await import(uri(turns))

test('Debug history visibility follows the session toggle while the raw transcript remains intact', () => {
  const scope = effectScope()
  const messages = ref([
    { id: 'story', role: 'assistant', content: 'An ordinary reply.' },
    { id: 'command', role: 'user', content: '/debug on', is_debug: true },
    { id: 'result', role: 'system', content: 'Enabled.', is_debug: true },
  ])
  const sheet = ref({ is_debug_enabled: false, debug_mode: true })
  const view = scope.run(() => useComicTurns({ messages, entities: ref([]), npcMetadata: ref({}), sheet }))
  const commands = () => view.gameTurns.value.flatMap(page => page.exchanges).filter(exchange => exchange.userMessage?.id === 'command')
  assert.equal(commands().length, 0)
  sheet.value.is_debug_enabled = true
  assert.equal(commands().length, 1)
  sheet.value.is_debug_enabled = false
  assert.equal(commands().length, 0)
  assert.equal(messages.value.length, 3)
  scope.stop()
})
const hover = uri(compile('services/hoverEntityService.ts'))
const placement = uri(compile('utils/gameHoverPlacement.ts'))
const hoverOwner = uri(compile('composables/useGameHoverTooltip.ts')
  .replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replaceAll("'@/services/hoverEntityService'", JSON.stringify(hover))
  .replaceAll("'@/utils/gameHoverPlacement'", JSON.stringify(placement)))
const interaction = compile('composables/useGameInteractionState.ts')
  .replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replaceAll("'./useGameHoverTooltip'", JSON.stringify(hoverOwner))
  .replaceAll("'@/utils/npcIdentity'", JSON.stringify(identity))
  .replaceAll("'@/services/hoverEntityService'", JSON.stringify(hover))
  .replaceAll("'@/services/gameCommandService'", JSON.stringify(uri('export const gameCommandService = {}')))
const {useGameInteractionState} = await import(uri(interaction))

const doctor = {id:'DR_AOYAMA',entity_type:'NPC',name:'Доктор Рин Аояма',description:'A physician.',image_url:'/rin.png'}

test('full and shortened dialogue labels keep the same NPC ID, name and portrait', () => {
  const result = parseAssistantContent('Доктор Рин: «Здравствуйте.»\nРин: «Пойдём.»\nРин: Я остаюсь здесь.', {}, [doctor])
  assert.equal(result.dialogues.length,3)
  for (const line of result.dialogues) {
    assert.equal(line.speakerEntity?.id,doctor.id)
    assert.equal(line.speaker,doctor.name)
    assert.equal(line.avatarUrl,doctor.image_url)
    assert.ok(!line.isNarration)
  }
})

test('hovering a shortened name returns the existing character instead of a new placeholder', t => {
  const scope=effectScope()
  t.after(()=>scope.stop())
  const turns=scope.run(()=>useComicTurns({messages:ref([]),entities:ref([doctor]),npcMetadata:ref({}),sheet:ref({})}))
  const hover=turns.getEntityForHover('Рин')
  assert.equal(hover.id,doctor.id)
  assert.equal(hover.image_url,doctor.image_url)
  assert.equal(turns.npcs.value.length,1)
})

test('metadata keyed by canonical ID retains that ID even without a scene entity', () => {
  const metadata={DR_AOYAMA:{name:doctor.name,image_url:doctor.image_url,entity_type:'NPC'}}
  assert.equal(resolveNpc('Рин',[],metadata)?.id,doctor.id)
  assert.equal(resolveNpcMetadata('Рин',metadata)?.id,doctor.id)
})

test('short names require whole name parts and must be unambiguous', () => {
  const nurse={id:'NURSE_RIN',entity_type:'NPC',name:'Медсестра Рин Судзуки'}
  assert.equal(resolveNpc('Рин',[doctor,nurse]),null)
  assert.equal(resolveNpc('Ри',[doctor]),null)
  assert.equal(resolveNpc('Ан',[{id:'ANNA',entity_type:'NPC',name:'Анна'}]),null)
  assert.equal(resolveNpc('Рин',[{id:'OBJECT',entity_type:'OBJECT',name:'Доктор Рин'}]),null)
})

test('explicit IDs and exact names take priority over short forms and learned aliases', () => {
  const other={id:'OTHER_RIN',entity_type:'NPC',name:'Рин'}
  assert.equal(resolveNpc('Рин',[doctor,other])?.id,other.id)
  assert.equal(resolveNpc(doctor.id,[doctor,other])?.id,doctor.id)
  const alias={...doctor,metadata_json:{npc_journal:{aliases:['Врач']}}}
  assert.equal(resolveNpc('Врач',[alias])?.id,doctor.id)
  assert.equal(resolveNpc('Врач',[alias,{...other,metadata_json:{npc_journal:{aliases:['Врач']}}}]),null)
})

test('name resolution uses only the current session cast and never caches a prior identity', () => {
  assert.equal(resolveNpc('Рин',[doctor])?.id,doctor.id)
  assert.equal(resolveNpc('Рин',[]),null)
  const next={...doctor,id:'SECOND_SESSION_RIN'}
  assert.equal(resolveNpc('Рин',[next])?.id,next.id)
})

test('classic hover uses the canonical identity and preserves all existing runtime fields', t => {
  const scope=effectScope()
  t.after(()=>scope.stop())
  const entity={...doctor,hp:0,armor_class:17,strength:12,custom_state:'preserve'}
  const state=scope.run(()=>useGameInteractionState({
    isActionInputBlocked:ref(false),npcMetadata:ref({}),npcEntities:ref([entity]),handlePlayerInput:async()=>{},
  }))
  state.handleChatNpcHover('Рин',{clientX:20,clientY:30})
  assert.equal(state.hoveredEntity.value.id,doctor.id)
  assert.equal(state.hoveredEntity.value.hp,0)
  assert.equal(state.hoveredEntity.value.armor_class,17)
  assert.equal(state.hoveredEntity.value.strength,12)
  assert.equal(state.hoveredEntity.value.custom_state,'preserve')
})

test('the same identity in scene entities and metadata is not an ambiguous second NPC', () => {
  const metadata={DR_AOYAMA:{name:doctor.name,image_url:doctor.image_url}}
  assert.equal(resolveNpc('Рин',[doctor],metadata)?.id,doctor.id)
  assert.equal(resolveNpc('Рин Аояма',[doctor],metadata)?.id,doctor.id)
})

test('technical captions stay narration even when a short word occurs in a character name', () => {
  const result=parseAssistantContent('Note: Remember the key.',{},[{id:'NPC_CAPTAIN',entity_type:'NPC',name:'Captain Note'}])
  assert.equal(result.dialogues[0].isNarration,true)
})

for (const [name,short] of [['Dr. Rin Aoyama','Rin'],['Élodie Martin','Élodie'],['明 山田','明'],['ليلى منصور','ليلى']]) {
  test(`unique whole name parts work across supported scripts: ${short}`,()=>{
    const entity={id:'PERSON',entity_type:'NPC',name}
    assert.equal(resolveNpc(short,[entity])?.id,entity.id)
  })
}

test('streaming a long page reuses settled dialogue and refreshes changed identities', t => {
  const scope = effectScope()
  t.after(() => scope.stop())
  const history = ref(Array.from({ length: 200 }, (_, i) => ({ id: String(i), role: 'assistant', content: `Доктор Рин: «Реплика ${i}.»`, scene_id: 'ROOM' })))
  const cast = ref([{ ...doctor }])
  const turns = scope.run(() => useComicTurns({ messages: history, entities: cast, npcMetadata: ref({}), sheet: ref({}) }))
  const first = turns.gameTurns.value[0].exchanges[0].dialogues[0]
  for (let i = 0; i < 100; i++) {
    history.value.at(-1).content = `Доктор Рин: «Поток ${i}.»`
    const page = turns.gameTurns.value[0]
    assert.equal(page.exchanges[0].dialogues[0], first)
    assert.equal(page.exchanges.at(-1).dialogues[0].text, `Поток ${i}.`)
  }
  cast.value[0].image_url = '/new-rin.png'
  const updated = turns.gameTurns.value[0].exchanges[0].dialogues[0]
  assert.notEqual(updated, first)
  assert.equal(updated.avatarUrl, '/new-rin.png')
})
