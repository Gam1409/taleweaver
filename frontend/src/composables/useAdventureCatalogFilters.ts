import { computed, ref, type Ref } from 'vue'
import type { AdventureLibraryItem } from '@/types/adventureLibrary'

/** Browsing stays independent of network access, installation and portal state. */
export function useAdventureCatalogFilters(items: Ref<AdventureLibraryItem[]>) {
  const query = ref('')
  const language = ref('')
  const languages = computed(() =>
    [...new Set(items.value.map(item => item.entry.language).filter(Boolean))].sort()
  )
  const filteredItems = computed(() => {
    const term = query.value.trim().toLocaleLowerCase()
    return items.value.filter(({ entry }) => {
      if (language.value && entry.language !== language.value) return false
      return (
        !term ||
        [entry.title, entry.teaser, entry.author].some(value =>
          (value || '').toLocaleLowerCase().includes(term)
        )
      )
    })
  })
  function clearFilters() {
    query.value = ''
    language.value = ''
  }
  return { query, language, languages, filteredItems, clearFilters }
}
