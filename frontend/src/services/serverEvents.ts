export interface ServerEvent<T> {
  event: string
  data: T
}

interface ReadOptions {
  signal?: AbortSignal
  isCurrent?: () => boolean
  onActivity?: () => void
}

function parseFrame<T>(frame: string): ServerEvent<T> | null {
  let event = 'message'
  const data: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith(':')) continue
    const separator = line.indexOf(':')
    const field = separator < 0 ? line : line.slice(0, separator)
    const value = separator < 0 ? '' : line.slice(separator + 1).replace(/^ /, '')
    if (field === 'event') event = value
    if (field === 'data') data.push(value)
  }
  if (data.length === 0) return null
  const payload: unknown = JSON.parse(data.join('\n'))
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('The server sent an invalid event payload.')
  }
  return { event, data: payload as T }
}

/** Shared chat/agent transport. EOF never confirms an unterminated event. */
export async function* readServerEvents<T>(
  body: ReadableStream<Uint8Array>,
  options: ReadOptions = {},
): AsyncGenerator<ServerEvent<T>> {
  const reader = body.getReader()
  const decoder = new TextDecoder('utf-8', { fatal: true })
  let buffer = ''
  let pendingCr = ''
  const abort = () => { void reader.cancel().catch(() => undefined) }
  options.signal?.addEventListener('abort', abort, { once: true })
  try {
    while (options.isCurrent?.() !== false) {
      if (options.signal?.aborted) throw new DOMException('Request aborted.', 'AbortError')
      const { value, done } = await reader.read()
      if (options.signal?.aborted) throw new DOMException('Request aborted.', 'AbortError')
      if (options.isCurrent?.() === false) return
      if (!done) options.onActivity?.()
      let text = pendingCr + decoder.decode(value, { stream: !done })
      pendingCr = !done && text.endsWith('\r') ? '\r' : ''
      if (pendingCr) text = text.slice(0, -1)
      buffer += text.replace(/\r\n?/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      let frames = 0
      let resumedAt = performance.now()
      while (boundary >= 0) {
        if (options.signal?.aborted) throw new DOMException('Request aborted.', 'AbortError')
        if (options.isCurrent?.() === false) return
        const event = parseFrame<T>(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        if (event) yield event
        // A proxy may deliver hundreds of tokens in one read. Promise-only
        // iteration starves painting, input handlers and the Abort button.
        if (++frames >= 32 || performance.now() - resumedAt >= 12) {
          await new Promise<void>(resolve => setTimeout(resolve, 0))
          frames = 0
          resumedAt = performance.now()
        }
        boundary = buffer.indexOf('\n\n')
      }
      if (done) return
    }
  } finally {
    options.signal?.removeEventListener('abort', abort)
    // Release abandoned reads on navigation; a closed transport can reject cancel.
    void reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
