import assert from 'node:assert/strict'

// One row per actual dialog surface, including internal confirmation windows.
export const authoringWindowCases = [
  { id: 'editor-delete', file: 'views/AdventureEditorView.vue', window: 0, portal: true },
  { id: 'editor-regenerate', file: 'views/AdventureEditorView.vue', window: 1, portal: true },
  { id: 'catalog', file: 'components/create-adventure/AdventureCatalogSelector.vue', fixture: 'catalog', action: 'catalog' },
  { id: 'create-options', file: 'components/create-adventure/AdventureClothingSettings.vue', fixture: 'create-options', action: 'gate' },
  { id: 'sequence-edit', file: 'components/editor/SequencesSection.vue', window: 0, fixture: 'sequences', title: 'Edit Sequence' },
  { id: 'sequence-delete', file: 'components/editor/SequencesSection.vue', window: 1, fixture: 'sequences', title: 'Delete Sequence' },
  { id: 'create-item', file: 'components/editor/ItemCreateDialog.vue', fixture: 'create-item' },
  { id: 'create-npc', file: 'components/editor/NpcCreateDialog.vue', fixture: 'create-npc' },
  { id: 'move', file: 'components/editor/MoveItemToSceneModal.vue', fixture: 'move' },
  { id: 'quest-edit', file: 'components/editor/QuestTab.vue', window: 0, fixture: 'quests', button: 'Edit' },
  { id: 'quest-delete', file: 'components/editor/QuestTab.vue', window: 1, fixture: 'quests', button: 'Delete' },
  { id: 'award-edit', file: 'components/editor/AwardsTab.vue', window: 0, fixture: 'awards', button: 'Edit' },
  { id: 'award-delete', file: 'components/editor/AwardsTab.vue', window: 1, fixture: 'awards', button: 'Delete' },
  { id: 'script-edit', file: 'components/editor/ScriptsTab.vue', window: 0, fixture: 'scripts', button: 'Edit' },
  { id: 'script-delete', file: 'components/editor/ScriptsTab.vue', window: 1, fixture: 'scripts', title: 'Delete Script' },
  { id: 'validation-delete', file: 'components/editor/ValidationTab.vue', fixture: 'validation', button: 'Delete all' },
  { id: 'edit-npc', file: 'components/editor/EditEntityModal.vue', fixture: 'edit-npc' },
  { id: 'item-type', file: 'components/editor/ItemTypeSelectorModal.vue', fixture: 'item-type' },
  { id: 'existing', file: 'components/editor/AddExistingItemModal.vue', fixture: 'existing' },
  { id: 'vision', file: 'components/editor/ManualVisionModal.vue', fixture: 'vision' },
  { id: 'debug', file: 'components/editor/DataDebugModal.vue', fixture: 'debug' },
  { id: 'exit', file: 'components/editor/EditExitModal.vue', fixture: 'exit' },
  { id: 'combat', file: 'components/editor/NpcCombatModal.vue', fixture: 'combat' },
  { id: 'suggestions', file: 'components/editor/AIFixSuggestionsModal.vue', fixture: 'suggestions' },
  { id: 'personality', file: 'components/editor/NpcPersonalityDetails.vue', fixture: 'personality', button: 'Details · Personality' },
  { id: 'concordia', file: 'components/living-world/ConcordiaSettingsModal.vue', fixture: 'concordia' },
  { id: 'editor-options', file: 'components/editor/ClothingDetailSettings.vue', fixture: 'editor-options', action: 'gate' },
  { id: 'protagonist-import', file: 'components/editor/ProtagonistImportConfirmDialog.vue', fixture: 'protagonist-import' },
]

async function editorSection(page, name, key) {
  await page.locator('.adventure-editor-view').waitFor()
  const mobile = page.locator('#editor-section')
  if (await mobile.isVisible()) await mobile.selectOption(key)
  else await page.getByRole('navigation', { name: 'Adventure sections' }).getByRole('button', { name, exact: true }).click()
}

async function openWindow(page, origin, entry) {
  if (entry.portal) {
    await page.goto(`${origin}/tests/browser/portalPreview.html?screen=editor`)
    if (entry.id === 'editor-regenerate') {
      await editorSection(page, 'Inhabitants', 'inhabitants')
      await page.getByRole('button', { name: /Regenerate All$/i }).click()
    } else {
      await editorSection(page, 'Items', 'items')
      await page.getByRole('button', { name: 'Actions for Sealed letter', exact: true }).click()
      await page.getByRole('button', { name: 'Delete', exact: true }).click()
    }
    return
  }
  await page.goto(`${origin}/tests/browser/authoringWindows.html?window=${entry.fixture}`)
  if (entry.action === 'catalog') await page.getByTitle('Click to change Visual style', { exact: true }).click()
  if (entry.action === 'gate') {
    if (entry.fixture === 'create-options') await page.locator('summary').click()
    await page.locator('main input[type="checkbox"]').nth(1).check()
  }
  if (entry.title) await page.getByTitle(entry.title, { exact: true }).click()
  if (entry.button) await page.getByRole('button', { name: new RegExp(entry.button + '$', 'i') }).click()
}

async function inspectWindow(page) {
  const panel = page.locator('.authoring-dialog:visible').last()
  await panel.waitFor()
  await page.waitForTimeout(150)
  const geometry = await panel.evaluate(node => {
    const box = node.getBoundingClientRect()
    // CodeMirror's clipped 1000px native input is an implementation detail, not its visible editor.
    const controls = [...node.querySelectorAll('button,input,select,textarea,.CodeMirror')].filter(item => item.checkVisibility() && !(item.tagName === 'TEXTAREA' && item.closest('.CodeMirror')))
    return {
      box: { x: box.x, y: box.y, right: box.right, bottom: box.bottom },
      viewport: { width: innerWidth, height: innerHeight },
      horizontalOverflow: node.scrollWidth > node.clientWidth,
      overflowingControls: controls.filter(item => { const r = item.getBoundingClientRect(); return r.left < box.left - 1 || r.right > box.right + 1 }).map(item => item.getAttribute('aria-label') || item.textContent?.trim().slice(0, 80) || item.tagName),
      background: getComputedStyle(node).backgroundColor,
      font: getComputedStyle(node).fontFamily,
      scrollers: [node, ...node.querySelectorAll('*')].filter(item => /auto|scroll/.test(getComputedStyle(item).overflowY) && item.scrollHeight > item.clientHeight + 1).length,
    }
  })
  assert.ok(geometry.box.x >= -1 && geometry.box.y >= -1 && geometry.box.right <= geometry.viewport.width + 1 && geometry.box.bottom <= geometry.viewport.height + 1, JSON.stringify(geometry))
  assert.equal(geometry.horizontalOverflow, false, JSON.stringify(geometry))
  assert.deepEqual(geometry.overflowingControls, [], JSON.stringify(geometry))
  assert.equal(geometry.background, 'rgb(16, 24, 39)')
  assert.match(geometry.font, /Alegreya Sans/)
  // Exercise real scrolling regions before using the real close control.
  const scrollFailures = await panel.evaluate(node => {
    const failures = []
    for (const region of [node, ...node.querySelectorAll('*')]) {
      if (!region.checkVisibility() || !region.clientHeight || !/auto|scroll/.test(getComputedStyle(region).overflowY) || region.scrollHeight <= region.clientHeight + 1) continue
      region.scrollTop = region.scrollHeight
      if (Math.abs(region.scrollTop - (region.scrollHeight - region.clientHeight)) > 1) failures.push(region.className)
      region.scrollTop = 0
    }
    return failures
  })
  assert.deepEqual(scrollFailures, [], 'Scrollable content must reach its last line')
  return { panel, geometry }
}

export async function checkAuthoringWindows(page, origin, options = {}) {
  page.setDefaultTimeout(15000)
  await page.route('https://cdn.jsdelivr.net/**', route => route.abort())
  const rows = []
  const cases = options.cases || authoringWindowCases
  const sizes = options.sizes || [[1440, 1000], [720, 500], [320, 568]]
  for (const [width, height] of sizes) {
    await page.setViewportSize({ width, height })
    for (const entry of cases) {
      const errors = []
      const onError = error => errors.push(error.message)
      page.on('pageerror', onError)
      const row = { id: entry.id, file: entry.file, window: entry.window || 0, width, height, status: 'pass' }
      try {
        await openWindow(page, origin, entry)
        const { panel, geometry } = await inspectWindow(page)
        row.geometry = geometry
        const cancel = panel.getByRole('button', { name: /^(Cancel|Discard|Close Inspector|Close)$/ }).first()
        const closer = await cancel.count() ? cancel : panel.getByRole('button').first()
        await closer.click()
        await panel.waitFor({ state: 'hidden' })
        assert.deepEqual(errors, [])
        const unhandled = await page.evaluate(() => window.authoringWindows?.unhandled || window.portalFixture?.unhandled || [])
        assert.deepEqual(unhandled, [], 'The fixture must account for every API boundary')
      } catch (error) {
        row.status = 'fail'
        row.error = error.message
        row.screenshot = `/tmp/authoring-window-${entry.id}-${width}.png`
        await page.screenshot({ path: row.screenshot }).catch(() => {})
      } finally {
        page.off('pageerror', onError)
      }
      rows.push(row)
      options.onRow?.(row)
    }
  }
  return rows
}
