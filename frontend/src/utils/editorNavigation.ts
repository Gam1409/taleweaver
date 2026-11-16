import { Globe2, Sparkles, ListTree, UserRound, Map, MapPin, UsersRound, Package, ScrollText, Trophy, Code2, Palette, Feather, Settings2, ShieldCheck, FileText } from 'lucide-vue-next'

const icons = {
  world: Globe2, 'living-world': Sparkles, sequences: ListTree, protagonist: UserRound,
  map: Map, scenes: MapPin, inhabitants: UsersRound, items: Package, quest: ScrollText,
  awards: Trophy, scripts: Code2, visuals: Palette, tone: Feather, advanced: Settings2,
  validation: ShieldCheck,
}

export function editorSectionIcon(key: string) {
  return icons[key as keyof typeof icons] || FileText
}
