import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {reactive} from 'vue'
import ts from 'typescript'

const quoteCode = ts.transpileModule(readFileSync(new URL('../src/utils/wardrobeQuotes.ts', import.meta.url), 'utf8'),
  {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}}).outputText
const quoteModule = `data:text/javascript;base64,${Buffer.from(quoteCode).toString('base64')}`
const script = readFileSync(new URL('../src/components/game/DebugRecoveryManual.vue', import.meta.url), 'utf8')
  .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  .replace(/import[^\n]+\n/g, '')
  .replace(/const props = defineProps<[\s\S]*?>\(\)/, '')
  .replace(/const emit = defineEmits<[^\n]+\n/, '')
const compiled = ts.transpileModule(`import {computed,ref} from '${import.meta.resolve('vue')}';
import {quoteError} from '${quoteModule}';
export function setup(props, emit) {
  ${script}
  return {sourceId,evidence,name,description,kind,status,attachment,clothing,slots,valid,submit,quoteIssue};
}`, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}}).outputText
const {setup} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const TEXT = 'Lina keeps a sealed tube in its recorded placement.'

function fixture() {
  const props = reactive({token:'manual',sources:{message:TEXT},busy:false})
  const commands = []
  return {props,commands,...setup(props,(_event,command)=>commands.push(command))}
}

test('a missing placed object uses a short known description and a source before previewing', () => {
  const f=fixture()
  f.sourceId.value='message'
  f.name.value='Sealed tube'
  f.description.value='A sealed tube.'
  f.attachment.value='vaginal'
  assert.equal(f.valid.value,false)
  f.evidence.value=TEXT
  assert.equal(f.valid.value,true)
  f.submit()
  assert.equal(f.commands.length,1)
  assert.ok(f.commands[0].startsWith('/debug wardrobe_add manual '))
  const body=JSON.parse(f.commands[0].slice('/debug wardrobe_add manual '.length))
  assert.deepEqual(body,{source_message_id:'message',evidence:TEXT,new_item:{kind:'ordinary',name:'Sealed tube',description:'A sealed tube.'},disposition:'worn',attachment_slot:'vaginal'})
  f.props.busy=true
  f.submit()
  assert.equal(f.commands.length,1)
})

test('garments require explicit metadata and do not inherit body-placement fields', () => {
  const f=fixture()
  f.sourceId.value='message'
  f.name.value='Red briefs'
  f.description.value='Red briefs.'
  f.kind.value='clothing'
  f.attachment.value='anal'
  f.status.value='carried'
  f.evidence.value=TEXT
  assert.equal(f.valid.value,false)
  f.clothing.value={layer:0,coverage:['pelvis'],underwear:true}
  f.slots.value=['Legs']
  assert.equal(f.valid.value,true)
  f.submit()
  const body=JSON.parse(f.commands[0].slice('/debug wardrobe_add manual '.length))
  assert.equal(body.disposition,'carried')
  assert.equal(body.new_item.kind,'clothing')
  assert.deepEqual(body.new_item.wearable_slots,['Legs'])
  assert.equal('attachment_slot' in body,false)
})

test('repeated body evidence and unknown sources cannot submit a manual draft', () => {
  const f=fixture()
  f.sourceId.value='message'
  f.name.value='Tube'
  f.description.value='Tube.'
  f.evidence.value=TEXT
  f.attachment.value='vaginal'
  f.props.sources.message=`${TEXT} ${TEXT}`
  assert.match(f.quoteIssue.value,/only once/)
  f.submit()
  assert.equal(f.commands.length,0)
  f.sourceId.value='unknown'
  assert.equal(f.valid.value,false)
})
