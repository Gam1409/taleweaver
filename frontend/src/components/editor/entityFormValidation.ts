interface EntityForm {
  name?: string
  description?: string
  goal?: string
  character?: string
  teaser?: string
  entity_id?: string
  clothing?: { layer?: number; coverage?: string[]; category?: string; opaque?: boolean } | null
  item_type?: string
  combination_ingredients_input?: string[]
  switch_initial_state?: string
}

interface ValidationOptions {
  hasEditableId: boolean
  maxIdLength: number
  entityIdError: string
  switchStates: string[]
  switchTransitions: { from?: string; to?: string }[]
}

/** The save button and its explanation must use the same validation result. */
export function entityFormErrors(form: EntityForm, options: ValidationOptions): string[] {
  const errors: string[] = []
  const fields = [
    ['name', 'Name', 50, true],
    ['description', 'Description / Biography', 1000, true],
    ['goal', 'Goal / Motivation', 300, false],
    ['character', 'Character / Traits', 300, false],
    ['teaser', 'Teaser', 300, false],
  ] as const
  for (const [key, label, limit, required] of fields) {
    const value = form[key] || ''
    if (required && !value.trim()) errors.push(`${label} is required.`)
    if (value.length > limit) errors.push(`${label}: ${value.length} characters; maximum ${limit}.`)
  }
  if (options.hasEditableId) {
    if (options.entityIdError) errors.push(`ID: ${options.entityIdError}`)
    if (!(form.entity_id || '').trim() && !options.entityIdError) errors.push('ID is required.')
    if ((form.entity_id || '').length > options.maxIdLength) errors.push(`ID must be at most ${options.maxIdLength} characters.`)
  }
  const itemType = String(form.item_type || '').toUpperCase()
  if (itemType === 'WEARABLE') {
    const clothing = form.clothing
    if (!clothing || !Number.isInteger(clothing.layer) || clothing.layer! < 0 || clothing.layer! > 4) errors.push('Clothing: select a layer or prepare missing clothing data.')
    const regions = ['head', 'torso', 'arms', 'pelvis', 'legs', 'feet', 'hands']
    const coverage = Array.isArray(clothing?.coverage) ? clothing.coverage : []
    if (!coverage.length || coverage.some(region => !regions.includes(region)) || new Set(coverage).size !== coverage.length) errors.push('Clothing: select valid, unique covered or placement regions.')
    if (clothing?.category && !['clothing', 'armor', 'accessory'].includes(clothing.category)) errors.push('Clothing: select a valid category.')
  }
  const ingredients = (form.combination_ingredients_input || []).filter(Boolean)
  if (itemType === 'CONSTRUCTABLE' && ingredients.length < 2) {
    errors.push('Constructable items require at least two ingredients.')
  }
  if (itemType !== 'SWITCH') return errors
  const states = options.switchStates
  const uniqueStates = new Set(states.map(state => state.trim().toUpperCase()))
  if (states.length < 2 || uniqueStates.size !== states.length || states.some(state => !state.trim())) {
    errors.push('Switch states: provide at least two non-empty, unique states.')
  }
  const initial = String(form.switch_initial_state || '').trim().toUpperCase()
  if (!initial || !uniqueStates.has(initial)) errors.push('Switch initial state must match a defined state.')
  if (options.switchTransitions.some(t => !t.to || !uniqueStates.has(t.to) || (t.from && !uniqueStates.has(t.from)))) {
    errors.push('Switch transitions must reference defined states and include a destination.')
  }
  return errors
}
