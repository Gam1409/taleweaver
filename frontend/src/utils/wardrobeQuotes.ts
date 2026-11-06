/** Quote assistance copies source text; it never relaxes exact evidence checks. */
export function quoteError(source: string, quote: string): string {
  if (!source) return 'The cited message is unavailable. Generate a new preview.'
  const exact = quote.trim()
  const length = [...exact].length
  if (length < 4) return 'Copy an exact quote of at least 4 characters from the cited message.'
  if (length > 800) return 'Use a shorter quote: at most 800 characters.'
  if (!source.includes(exact))
    return 'This quote was not found in the cited message. Copy the original text, including its case, punctuation and spaces.'
  return ''
}

export function quoteSuggestion(source: string, quote: string): string {
  const exact = quote.trim()
  const words = exact.split(/\s+/u)
  if ([...exact].length < 4 || [...exact].length > 800 || !words[0] || source.includes(exact)) return ''
  const pattern = words.map(word => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+')
  const matches = source.matchAll(new RegExp(`(?=(${pattern}))`, 'giu'))
  const first = matches.next().value?.[1]
  // Ambiguous matches need an explicit source selection, not a guessed occurrence.
  return first && matches.next().done && !quoteError(source, first) ? first : ''
}
