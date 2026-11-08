import type { ItemDraft } from '@/services/itemGeneration'

/** Map a generated draft to editable fields without replacing manual rules or IDs. */
export function itemDraftFields(draft: ItemDraft) {
  return {
    name: draft.name,
    description: draft.description,
    is_portable: draft.is_portable,
    wearable_slots_input: [...draft.wearable_slots],
    text_log_content: draft.text_log_content,
    clothing: draft.clothing ? { ...draft.clothing, coverage: [...draft.clothing.coverage] } : null,
  }
}
