import { test } from 'node:test'
import assert from 'node:assert/strict'
import { authoringFixture, modalFixture } from './authoringPersistenceFixture.mjs'

function createObject(type) {
  const editor = authoringFixture()
  editor.createEntitySceneId.value = 'LAB'
  editor.handleItemTypeSelected(type)
  return editor
}

test('container modal creation persists lock, guard, events and explicit portability', async t => {
  const editor = createObject('CONTAINER'), modal = modalFixture(t, editor)
  modal.update({ entity_id: 'CHEST_FIXTURE', name: 'Supply chest', description: 'A sturdy supply chest.',
    is_portable: false, locked: true, code_to_unlock: '1234', unlock_expression: "tw.vars.get('permit', False)",
    on_unlock_success_script: "tw.vars.set('opened', True)", on_unlock_failure_text: 'The latch stays closed.',
    pickup_trigger_mode: 'narration', pickup_trigger_cue: 'The chest is heavy.',
  })
  await modal.submit()
  const request = editor.requests.at(-1)
  assert.equal(request.method, 'POST')
  assert.equal(request.data.is_portable, false)
  assert.equal(request.data.metadata_json.locked, true)
  assert.equal(request.data.metadata_json.code_to_unlock, '1234')
  assert.equal(request.data.metadata_json.unlock_expression, "tw.vars.get('permit', False)")
  assert.equal(request.data.metadata_json.on_unlock_success_script, "tw.vars.set('opened', True)")
  assert.equal(request.data.metadata_json.on_unlock_failure_text, 'The latch stays closed.')
  assert.deepEqual(request.data.metadata_json.pickup_trigger, { mode: 'narration', cue: 'The chest is heavy.' })
})

test('readable and constructable creation keep their displayed rule and event fields', async t => {
  const readable = createObject('READABLE'), readModal = modalFixture(t, readable)
  readModal.update({ entity_id: 'NOTICE_FIXTURE', text_log_content: 'A technical notice.', text_log_format: 'SIGN',
    on_read_script: "tw.vars.set('read', True)", on_read_text: 'The notice is legible.', is_portable: false })
  await readModal.submit()
  const text = readable.requests.at(-1).data.metadata_json
  assert.equal(text.text_log_content, 'A technical notice.')
  assert.equal(text.text_log_format, 'SIGN')
  assert.equal(text.on_read_script, "tw.vars.set('read', True)")
  assert.equal(text.on_read_text, 'The notice is legible.')
  const craft = createObject('CONSTRUCTABLE'), craftModal = modalFixture(t, craft)
  craftModal.update({ entity_id: 'ASSEMBLY_FIXTURE', combination_ingredients_input: ['PART_A', 'PART_B'],
    craft_guard_expression: "tw.vars.get('ready', False)", on_craft_success_text: 'The assembly fits.', on_craft_failure_script: "tw.vars.set('retry', True)" })
  await craftModal.submit()
  assert.equal(craft.requests.at(-1).data.metadata_json.craft_guard_expression, "tw.vars.get('ready', False)")
  assert.equal(craft.requests.at(-1).data.metadata_json.on_craft_success_text, 'The assembly fits.')
  assert.equal(craft.requests.at(-1).data.metadata_json.on_craft_failure_script, "tw.vars.set('retry', True)")
})

test('switch modal creation and edit preserve independent global handlers and explicit clearing', async t => {
  const editor = createObject('SWITCH'), modal = modalFixture(t, editor)
  modal.update({ entity_id: 'SW_FIXTURE', switch_initial_state: 'OFF', on_success_script: "tw.vars.set('success', True)", on_failure_script: "tw.vars.set('failure', True)" })
  await modal.submit()
  const config = editor.requests.at(-1).data.metadata_json.switch
  assert.equal(config.on_success_script, "tw.vars.set('success', True)")
  assert.equal(config.on_failure_script, "tw.vars.set('failure', True)")
  editor.editorSwitches.value = [{ id: 'SW_FIXTURE', name: 'Control switch', description: 'A control switch.', item_type: 'SWITCH', metadata_json: { switch: config } }]
  editor.openTextEdit('object', 'SW_FIXTURE', 'Control switch', 'A control switch.')
  assert.equal(editor.editForm.value.on_success_script, config.on_success_script)
  assert.equal(editor.editForm.value.on_failure_script, config.on_failure_script)
  const editModal = modalFixture(t, editor)
  editModal.update({ on_success_script: '', on_failure_script: '' })
  await editModal.submit()
  assert.equal(editor.requests.at(-1).data.on_success_script, '')
  assert.equal(editor.requests.at(-1).data.on_failure_script, '')
})

for (const value of ['', undefined, "tw.vars.set('canonical', True)"]) {
  test(`unrelated switch edit preserves canonical nested global ${String(value)}`, async t => {
    const editor = authoringFixture()
    const stale = "tw.vars.set('stale', True)"
    const config = { states: ['OFF', 'ON'], initial_state: 'OFF', transitions: [] }
    if (value !== undefined) Object.assign(config, { on_success_script: value, on_failure_script: value })
    editor.editorSwitches.value = [{ id: 'SW_FIXTURE', item_type: 'SWITCH', on_success_script: stale,
      on_failure_script: stale, metadata_json: { on_success_script: stale, on_failure_script: stale, switch: config } }]
    editor.openTextEdit('object', 'SW_FIXTURE', 'Control switch', 'A control switch.')
    const modal = modalFixture(t, editor)
    modal.update({ name: 'Renamed control switch' })
    await modal.submit()
    assert.equal(editor.requests.at(-1).data.on_success_script, value ?? '')
    assert.equal(editor.requests.at(-1).data.on_failure_script, value ?? '')
  })
}

for (const type of ['npc', 'protagonist']) {
  test(`${type} modal editing preserves explicit zero resources`, async t => {
    const editor = authoringFixture()
    editor.openTextEdit(type, 'ACTOR_FIXTURE', 'Ari', 'A careful technician.', '', 20, 20, 20)
    const modal = modalFixture(t, editor)
    modal.update({ hp: 0, stamina: 0, mana: 0 })
    await modal.submit()
    assert.equal(editor.requests.at(-1).data.hp, 0)
    assert.equal(editor.requests.at(-1).data.stamina, 0)
    assert.equal(editor.requests.at(-1).data.mana, 0)
  })
}

for (const value of [0, 23]) test(`manual NPC creation keeps resource value ${value}`, async t => {
  const editor = authoringFixture()
  editor.openCreateNpc('LAB')
  const modal = modalFixture(t, editor)
  modal.update({ entity_id: 'NPC_ZERO_FIXTURE', hp: value, stamina: value, mana: value })
  await modal.submit()
  const data = editor.requests.at(-1).data
  assert.deepEqual([data.hp, data.stamina, data.mana], [value, value, value])
})

for (const value of ['', null, undefined]) {
  test(`empty resource ${String(value)} stays absent on edit and defaults on creation`, async t => {
    for (const type of ['npc', 'protagonist']) {
      const editor = authoringFixture()
      editor.openTextEdit(type, 'ACTOR_FIXTURE', 'Ari', 'A careful technician.', '', 23, 23, 23)
      const modal = modalFixture(t, editor)
      modal.update({ hp: value, stamina: value, mana: value })
      await modal.submit()
      const data = editor.requests.at(-1).data
      assert.equal('hp' in data, false)
      assert.equal('stamina' in data, false)
      assert.equal('mana' in data, false)
    }
    const editor = authoringFixture()
    editor.openCreateNpc('LAB')
    const modal = modalFixture(t, editor)
    modal.update({ hp: value, stamina: value, mana: value })
    await modal.submit()
    const data = editor.requests.at(-1).data
    assert.deepEqual([data.hp, data.stamina, data.mana], [20, 20, 20])
  })
}
