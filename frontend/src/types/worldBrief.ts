export interface WorldReference { url: string; excerpt: string; note: string }
export interface WorldBrief {
  setting: string
  history: string
  opening: string
  world_rules: string
  characters: string
  open_threads: string
  references: WorldReference[]
}
