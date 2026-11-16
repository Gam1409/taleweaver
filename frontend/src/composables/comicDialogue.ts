/** Conservative display parsing: ambiguous colon prose stays narration. */
import type { DialogueSegment } from './comicPages'

export interface SpeakerIdentity {
  name?: unknown
  id?: unknown
  entity_type?: unknown
  metadata_json?: { npc_journal?: { aliases?: unknown } }
}

export function speakerAliases(entity: SpeakerIdentity): string[] {
  const aliases = entity.metadata_json?.npc_journal?.aliases
  return Array.isArray(aliases) ? aliases.filter((value): value is string => typeof value === 'string') : []
}

export function resolveSpeakerAlias(name: string, entities: readonly SpeakerIdentity[]): SpeakerIdentity | null {
  const normalized = name.trim().toLowerCase()
  const matches = entities.filter(entity =>
    (!entity.entity_type || String(entity.entity_type).toUpperCase() === 'NPC') &&
    speakerAliases(entity).some(alias => alias.trim().toLowerCase() === normalized))
  return matches.length === 1 ? matches[0]! : null
}
export interface DialogueOptions {
  playerName?: string
  playerAvatar?: string | null
  knownNames: ReadonlySet<string>
  resolveSpeaker: (name: string) => DialogueSegment['speakerEntity']
}

const NON_SPEAKER_LABELS = new Set([
  'note',
  'warning',
  'caution',
  'info',
  'location',
  'status',
  'time',
  'goal',
  'quest',
  'tip'
])

export function knownSpeakerNames(
  playerName?: string,
  entities: readonly SpeakerIdentity[] = [],
  metadata: Record<string, unknown> = {}
): Set<string> {
  const records = Object.values(metadata).filter(
    (value): value is SpeakerIdentity => typeof value === 'object' && value !== null
  )
  const characters = entities.filter(
    entity => !entity.entity_type || String(entity.entity_type).toUpperCase() === 'NPC'
  )
  const names = [
    'you',
    playerName,
    ...Object.keys(metadata),
    ...[...characters, ...records].flatMap(entity => [entity.name, entity.id, ...speakerAliases(entity)])
  ]
  return new Set(
    names
      .filter((name): name is string => typeof name === 'string' && !!name.trim())
      .map(name => name.trim().toLowerCase())
  )
}

function isDialogueSpeaker(name: string, quoted: boolean, known: ReadonlySet<string>, resolved = false): boolean {
  if (known.has(name.toLowerCase())) return true
  if (NON_SPEAKER_LABELS.has(name.toLowerCase())) return false
  if (resolved) return true
  // New characters may speak before their metadata arrives. Require quoted speech
  // and a name-like label; punctuation in a known character's exact name is allowed.
  return (
    quoted &&
    /^[\p{L}\p{M}\p{N}_ .’'()-]{1,60}$/u.test(name)
  )
}

function appendNarration(dialogues: DialogueSegment[], line: string): void {
  let narrationText = line
  let voiceTag: string | undefined = undefined
  const tagMatch = narrationText.match(/^\[([^\]\n]+)\]\s*(.*)$/)
  if (tagMatch) {
    voiceTag = normalizeVoiceTag(tagMatch[1])
  }

  if (!narrationText || /^(?:[*_]{1,3}|[•·])$/u.test(narrationText)) return
  const last = dialogues[dialogues.length - 1]
  if (last && !last.isNarration) {
    // Quoted dialogue is split before its trailing punctuation. Keep that
    // punctuation with its speech rather than making an empty narrator card.
    const trailing = narrationText.match(/^([.,;:])(?:\s+|$)(.*)$/u)
    if (trailing) {
      if (!last.text.endsWith(trailing[1]!)) last.text += trailing[1]
      narrationText = trailing[2]!.trim()
      if (!narrationText) return
    }
  }
  if (last && last.isNarration) {
    last.text += '\n\n' + narrationText
    // Use the voice tag from the first paragraph if the new one doesn't have one
    if (voiceTag && !last.voiceTag) {
      last.voiceTag = voiceTag
    }
  } else {
    dialogues.push({ speaker: 'Game Master', text: narrationText, isNarration: true, voiceTag })
  }
}

/** Voice tags are always English; only normalize casing and whitespace. */
export function normalizeVoiceTag(tag: string): string {
  return tag.trim().toLowerCase()
}

export function parseComicDialogue(
  content: string,
  options: DialogueOptions
): { narration: string; dialogues: DialogueSegment[] } {
  if (!content) return { narration: '', dialogues: [] }

  const { knownNames } = options
  const dialogues: DialogueSegment[] = []
  let cleanContent = content.replace(/\\n/g, '\n').trim()

  // 1) Pre-split embedded/inline dialogues onto separate lines:
  // Detects: (Sentence end, voice tag, or line boundary) -> Speaker: "Dialogue"
  const knownPattern = [...knownNames]
    .sort((a, b) => b.length - a.length)
    .map(name => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|')
  const unknownPattern = String.raw`(?:\p{Lu}[\p{L}]{0,2}\.\s+)*[\p{L}\p{N}_][\p{L}\p{M}\p{N}_ \t'’\-()]{0,59}?`
  const namePattern = knownPattern ? `(?:${knownPattern}|${unknownPattern})` : unknownPattern
  // Close the same quote style that opened the speech. Inner guillemets in
  // straight/curly quoted dialogue are content, not a return to narration.
  const quotedSpeech = String.raw`(?:"[^"\n]*"|“[^”\n]*”|„[^“”\n]*[“”]|«(?:[^«»\n]|«[^«»\n]*»)*»|»[^«\n]*«)`
  const inlineSpeechSplitter = new RegExp(
    String.raw`(?:^|\n|(?<=[.!?»”"“]\s+)|(?<=\]\s*))(?:\[[^\]\n]+\]\s*)?(?:\*\*([^*\n:]{1,60}?):\*\*|\*\*([^*\n:]{1,60}?)\*\*:|(${namePattern}):)\s*(?:(?:\[[^\]\n]+\]|"\[[^"\n]+\]")\s*)?(${quotedSpeech})`,
    'giu'
  )
  cleanContent = cleanContent.replace(inlineSpeechSplitter, (match, bold, boldAfter, plain) => {
    const name = (bold || boldAfter || plain || '').replace(/\s+(?:to|\(to)\s+.+?\)?$/i, '').trim()
    return isDialogueSpeaker(name, true, knownNames) ? '\n\n' + match.trim() + '\n\n' : match
  })

  const lines = cleanContent.split('\n')

  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line) continue
    const dialogue = parseDialogueLine(line, options)
    if (dialogue) dialogues.push(dialogue)
    else appendNarration(dialogues, line)
  }

  // To keep compatibility, extract the first narration block as .narration
  // though the UI should iterate dialogues.
  const firstNarration = dialogues.find(d => d.isNarration)
  return {
    narration: firstNarration ? firstNarration.text : '',
    dialogues
  }
}

/** Accept legacy tags around quotes, but never infer a speaker from a colon alone. */
function parseDialogueLine(line: string, options: DialogueOptions): DialogueSegment | null {
  const match = line.match(
    /^(?:\[([^\]\n]+)\]\s*)?(?:(\*\*([^*:\n]+?):\*\*)|(\*\*([^*:\n]+?)\*\*:)|([\p{L}\p{M}\p{N}_ \t'’\-,.()]{1,60}):)\s*(.*)$/u
  )
  if (!match) return null
  const { playerName, playerAvatar, knownNames, resolveSpeaker } = options
  let speakerName = (match[3] || match[5] || match[6] || '').trim()
  let voiceTag = match[1] ? normalizeVoiceTag(match[1]) : undefined
  let inlineVoiceTag: string | undefined
  let speechText = (match[7] || '').trim()
  const tagInSpeech = speechText.match(/^"?\[([^\]\n]+)\]"?\s*"?\s*([\s\S]*)$/)
  if (tagInSpeech) {
    if (voiceTag) inlineVoiceTag = tagInSpeech[1]
    voiceTag = voiceTag || normalizeVoiceTag(tagInSpeech[1])
    speechText = tagInSpeech[2].trim()
  }
  const hasQuotes = /^["“„«»]/.test(speechText) || /["”«»]$/.test(speechText)
  // Remove only the outer delimiters; preserve quotes within the spoken text.
  speechText = speechText.replace(/^["“„«»]/, '').replace(/["”«»]$/, '').trim()
  if (inlineVoiceTag) speechText = `[${inlineVoiceTag}] ${speechText}`
  let targetName: string | undefined
  const toMatch = speakerName.match(/^(.+?)\s+(?:to|\(to)\s+(.+?)\)?$/i)
  if (toMatch) {
    speakerName = toMatch[1].trim()
    targetName = toMatch[2].trim()
  }
  const resolvedNpc = resolveSpeaker(speakerName)
  if (!isDialogueSpeaker(speakerName, hasQuotes, knownNames, Boolean(resolvedNpc))) return null
  const isPlayer =
    speakerName.toLowerCase() === 'you' ||
    speakerName.toLowerCase() === (playerName || '').toLowerCase()
  return {
    speaker: isPlayer ? playerName || 'You' : resolvedNpc?.name || speakerName,
    speakerEntity: isPlayer ? undefined : resolvedNpc,
    target: targetName,
    targetEntity: targetName ? resolveSpeaker(targetName) : undefined,
    avatarUrl: isPlayer ? playerAvatar : resolvedNpc?.image_url,
    isPlayer,
    text: speechText,
    voiceTag
  }
}


/** Reuse settled replies while the current message streams; weak keys release old history. */
export function cachedComicDialogue(options: DialogueOptions) {
  type Parsed = ReturnType<typeof parseComicDialogue>
  const replies = new WeakMap<object, { content: string; parsed: Parsed }>()
  return (content: string, message?: object): Parsed => {
    const cached = message && replies.get(message)
    if (cached && cached.content === content) return cached.parsed
    const parsed = parseComicDialogue(content, options)
    if (message) replies.set(message, { content, parsed })
    return parsed
  }
}
