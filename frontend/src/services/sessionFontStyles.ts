import type { SessionFont } from '@/utils/sessionTypography'

const styles = {
  'alegreya-sans': () => Promise.resolve(),
  'baloo-bhaijaan-2': () => import('@/assets/session-fonts/baloo-bhaijaan-2.css'),
  'm-plus-rounded-1c': () => import('@/assets/session-fonts/m-plus-rounded-1c.css'),
  'noto-sans-sc': () => import('@/assets/session-fonts/noto-sans-sc.css'),
  'noto-sans-tc': () => import('@/assets/session-fonts/noto-sans-tc.css'),
  'noto-sans-kr': () => import('@/assets/session-fonts/noto-sans-kr.css')
}

export function loadSessionFontStyle(font: SessionFont) {
  return styles[font]()
}
