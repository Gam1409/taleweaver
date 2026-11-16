export const CONTENT_LANGUAGES = [
  { code: '', name: 'Use default', icon: 'ra-spear-head' },
  { code: 'Arabic', name: 'العربية', icon: 'ra-scroll-unfurled', locale: 'ar' },
  { code: 'German', name: 'Deutsch', icon: 'ra-castle', locale: 'de' },
  { code: 'English', name: 'English', icon: 'ra-tower', locale: 'en' },
  { code: 'French', name: 'Français', icon: 'ra-fleur-de-lis', locale: 'fr' },
  { code: 'Spanish', name: 'Español', icon: 'ra-shield', locale: 'es' },
  { code: 'Italian', name: 'Italiano', icon: 'ra-scroll-unfurled', locale: 'it' },
  { code: 'Japanese', name: '日本語', icon: 'ra-shinto-shrine', locale: 'ja' },
  { code: 'Chinese', name: '简体中文', icon: 'ra-dragon', locale: 'zh-Hans' },
  { code: 'Traditional Chinese', name: '繁體中文', icon: 'ra-dragon', locale: 'zh-Hant' },
  { code: 'Korean', name: '한국어', icon: 'ra-scroll-unfurled', locale: 'ko' },
  { code: 'Russian', name: 'Русский', icon: 'ra-hammer', locale: 'ru' },
  { code: 'Portuguese', name: 'Português', icon: 'ra-anchor', locale: 'pt' }
] as const

const FONTS = {
  latin: { family: 'Alegreya Sans', asset: 'alegreya-sans', script: 'latin' },
  ar: { family: 'Baloo Bhaijaan 2', asset: 'baloo-bhaijaan-2', script: 'arabic' },
  ja: { family: 'M PLUS Rounded 1c', asset: 'm-plus-rounded-1c', script: 'cjk' },
  zh: { family: 'Noto Sans SC', asset: 'noto-sans-sc', script: 'cjk' },
  'zh-hant': { family: 'Noto Sans TC', asset: 'noto-sans-tc', script: 'cjk' },
  ko: { family: 'Noto Sans KR', asset: 'noto-sans-kr', script: 'cjk' }
} as const
export type SessionFont = (typeof FONTS)[keyof typeof FONTS]['asset']

/** Use the persisted Bable Fish language, including legacy names and locale aliases. */
export function sessionTypography(language: string) {
  const token = language.trim().toLowerCase().replace(/_/g, '-')
  const named = CONTENT_LANGUAGES.find(item => item.code.toLowerCase() === token)
  const locale = (named && 'locale' in named ? named.locale : token || 'en').toLowerCase()
  const parts = locale.split('-')
  const traditional =
    parts[0] === 'zh' && (parts[1] === 'hant' ||
      (parts[1] !== 'hans' && parts.some(part => ['tw', 'hk', 'mo'].includes(part))))
  const key = traditional ? 'zh-hant' : parts[0]!
  const font = FONTS[key as keyof typeof FONTS] || FONTS.latin
  return {
    ...font,
    locale: traditional ? 'zh-Hant' : locale,
    familyStack: `"${font.family}", "Alegreya Sans", sans-serif`
  }
}

/** Keep existing mixed-language history readable without reversing UI controls. */
export function proseDirection(text: string): 'rtl' | 'ltr' {
  const first = text.match(/\p{Letter}/u)?.[0] || ''
  return /\p{Script=Arabic}|\p{Script=Hebrew}/u.test(first) ? 'rtl' : 'ltr'
}
