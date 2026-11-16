import { onScopeDispose, watch, type Ref } from 'vue'
import { sessionTypography } from '@/utils/sessionTypography'
import { loadSessionFontStyle } from '@/services/sessionFontStyles'

/** Typography follows the confirmed session language and resets when leaving the game. */
export function useSessionTypography(language: Ref<string>) {
  const root = document.documentElement
  const initialFont = root.style.getPropertyValue('--session-font')
  const attributes = ['data-session-font', 'data-session-script', 'data-session-locale']
  const initial = attributes.map(name => root.getAttribute(name))
  watch(
    language,
    value => {
      const font = sessionTypography(value)
      root.style.setProperty('--session-font', font.familyStack)
      root.setAttribute('data-session-font', font.family)
      root.setAttribute('data-session-script', font.script)
      root.setAttribute('data-session-locale', font.locale)
      void loadSessionFontStyle(font.asset).catch(cause => {
        console.warn('Could not load the selected session font; using the local fallback.', cause)
      })
    },
    { immediate: true }
  )
  onScopeDispose(() => {
    if (initialFont) root.style.setProperty('--session-font', initialFont)
    else root.style.removeProperty('--session-font')
    attributes.forEach((name, index) => {
      const value = initial[index]
      if (value === null || value === undefined) root.removeAttribute(name)
      else root.setAttribute(name, value)
    })
  })
}
