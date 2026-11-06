/** Narrator-authored display data. Never infer psychology from prose or relationships. */
export interface PortraitPreferences {
  emotion_palette: boolean
  character_thoughts: boolean
  brightness: number
}
export interface PortraitCue {
  emotion?: string
  intensity?: number
  thought?: string
}
export interface PortraitState {
  version: 1
  source_hash: string
  npcs: Record<string, PortraitCue>
}
export const DEFAULT_PORTRAIT_PREFERENCES: PortraitPreferences = {
  emotion_palette: false, character_thoughts: false, brightness: 40,
}

// A game palette, not a universal psychological diagnosis. Fear has a dark core and pale rim.
export const EMOTION_PALETTE: Record<string, { label: string; rgb: string; rim?: string }> = {
  calm: { label: 'Calm', rgb: '125,211,252' },
  joy: { label: 'Joy', rgb: '250,204,21' },
  affection: { label: 'Affection', rgb: '253,164,175' },
  love: { label: 'Love', rgb: '244,63,94', rim: '249,168,212' },
  sexual_arousal: { label: 'Arousal', rgb: '236,72,153' },
  ecstasy: { label: 'Ecstasy', rgb: '232,121,249' },
  anger: { label: 'Anger', rgb: '239,68,68' },
  fear: { label: 'Fear', rgb: '12,10,18', rim: '148,140,165' },
  sadness: { label: 'Sadness', rgb: '99,102,241' },
  embarrassment: { label: 'Embarrassment', rgb: '251,146,174' },
  shame: { label: 'Shame', rgb: '167,139,180' },
  surprise: { label: 'Surprise', rgb: '253,230,138' },
  interest: { label: 'Interest', rgb: '45,212,191' },
  trust: { label: 'Trust', rgb: '110,231,183' },
  hope: { label: 'Hope', rgb: '190,242,100' },
  anxiety: { label: 'Anxiety', rgb: '196,181,253' },
  disgust: { label: 'Disgust', rgb: '132,163,66' },
  confusion: { label: 'Confusion', rgb: '165,180,252' },
  determination: { label: 'Determination', rgb: '251,146,60' },
  tiredness: { label: 'Tiredness', rgb: '148,163,184' },
  boredom: { label: 'Boredom', rgb: '161,161,170' },
}

export function parsePortraitPreferences(data: unknown): PortraitPreferences {
  const p = data as Partial<PortraitPreferences> | null
  if (typeof p?.emotion_palette !== 'boolean' || typeof p.character_thoughts !== 'boolean' ||
      typeof p.brightness !== 'number' || !Number.isInteger(p.brightness) || p.brightness < 0 || p.brightness > 100) {
    throw new Error('The server returned invalid portrait settings.')
  }
  return { emotion_palette: p.emotion_palette, character_thoughts: p.character_thoughts, brightness: p.brightness }
}

export function portraitPreferences(data: unknown): PortraitPreferences {
  try { return parsePortraitPreferences(data) } catch { return { ...DEFAULT_PORTRAIT_PREFERENCES } }
}

export function thoughtText(cue: PortraitCue | undefined, prefs: PortraitPreferences): string {
  const text = cue?.thought
  return prefs.character_thoughts && typeof text === 'string' && [...text].length <= 160 ? text.trim() : ''
}

export function emotionLabel(cue: PortraitCue | undefined, prefs: PortraitPreferences): string {
  if (!prefs.emotion_palette || !cue?.emotion || !Object.prototype.hasOwnProperty.call(EMOTION_PALETTE, cue.emotion) ||
      !Number.isInteger(cue.intensity) || cue.intensity! < 0 || cue.intensity! > 100) return ''
  return `${EMOTION_PALETTE[cue.emotion]!.label} · ${cue.intensity}%`
}

export function portraitStyle(cue: PortraitCue | undefined, prefs: PortraitPreferences): Record<string, string> {
  if (!emotionLabel(cue, prefs) || !prefs.brightness || !cue?.intensity) return {}
  const color = EMOTION_PALETTE[cue.emotion!]!
  const power = cue.intensity / 100 * prefs.brightness / 100
  return {
    borderColor: `rgba(${color.rim || color.rgb},${0.2 + power * 0.7})`,
    boxShadow: `0 0 ${8 + power * 26}px rgba(${color.rgb},${power * 0.75}), inset 0 0 ${6 + power * 14}px rgba(${color.rim || color.rgb},${power * 0.3})`,
  }
}

/** The latest narration on the viewed page owns its cues. Never borrow a past assessment. */
export function pagePortraitCues(exchanges: Array<{ assistantMessage?: { portrait_state?: PortraitState | null } | null }>): Record<string, PortraitCue> {
  const latest = [...exchanges].reverse().find(entry => entry.assistantMessage)?.assistantMessage
  return latest?.portrait_state?.version === 1 ? latest.portrait_state.npcs : {}
}
