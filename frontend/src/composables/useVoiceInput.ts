import { ref, watch, onMounted, onBeforeUnmount, type Ref } from 'vue'

export interface UseVoiceInputOptions {
  canSendInput: Ref<boolean>
  inputText: Ref<string>
  onSend: () => void
  sessionId?: Readonly<Ref<string | undefined>>
}

interface VoiceCapture {
  sessionId: string | undefined
  prefixSay: boolean
  request: AbortController
  chunks: Float32Array[]
  startedAt: number
  stream: MediaStream | null
  context: AudioContext | null
  source: MediaStreamAudioSourceNode | null
  processor: ScriptProcessorNode | null
}

function writeString(view: DataView, offset: number, string: string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i))
  }
}

function bufferToWav(buffer: Float32Array, sampleRate: number): ArrayBuffer {
  const bufferLength = buffer.length
  const wavBuffer = new ArrayBuffer(44 + bufferLength * 2)
  const view = new DataView(wavBuffer)

  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + bufferLength * 2, true)
  writeString(view, 8, 'WAVE')
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeString(view, 36, 'data')
  view.setUint32(40, bufferLength * 2, true)

  let offset = 44
  for (let i = 0; i < buffer.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, buffer[i]))
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return wavBuffer
}

export function useVoiceInput(options: UseVoiceInputOptions) {
  const { canSendInput, inputText, onSend } = options
  const sessionId = options.sessionId ?? ref<string>()
  const isRecording = ref(false)
  const isTranscribing = ref(false)
  const pttKeyPressed = ref(false)
  const pttPrefixSay = ref(false)
  const pttKeyActiveCode = ref('')
  let current: VoiceCapture | null = null
  let disposed = false
  let draftRevision = 0
  let globalMouseUpListener: (() => void) | null = null

  function owns(capture: VoiceCapture) {
    return !disposed && current === capture && capture.sessionId === sessionId.value && canSendInput.value
  }

  function releaseMedia(capture: VoiceCapture) {
    if (capture.processor) {
      capture.processor.onaudioprocess = null
      capture.processor.disconnect()
      capture.processor = null
    }
    capture.source?.disconnect()
    capture.source = null
    capture.stream?.getTracks().forEach(track => track.stop())
    capture.stream = null
    const context = capture.context
    capture.context = null
    if (context && context.state !== 'closed') {
      void context.close().catch(error => console.error('Failed to close voice audio:', error))
    }
  }

  function clearMouseUpListener() {
    if (!globalMouseUpListener) return
    window.removeEventListener('mouseup', globalMouseUpListener)
    window.removeEventListener('touchend', globalMouseUpListener)
    globalMouseUpListener = null
  }

  function finish(capture: VoiceCapture) {
    releaseMedia(capture)
    capture.chunks = []
    if (current !== capture) return
    current = null
    isRecording.value = false
    isTranscribing.value = false
    clearMouseUpListener()
  }

  function cancelVoiceRecording() {
    const capture = current
    if (capture) {
      capture.request.abort()
      finish(capture)
    }
    pttKeyPressed.value = false
    pttKeyActiveCode.value = ''
    clearMouseUpListener()
  }

  async function startVoiceRecording() {
    if (disposed || current || !canSendInput.value) return
    const capture: VoiceCapture = {
      sessionId: sessionId.value, prefixSay: pttPrefixSay.value, request: new AbortController(),
      chunks: [], startedAt: 0, stream: null, context: null, source: null, processor: null,
    }
    current = capture
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      capture.stream = stream
      if (!owns(capture)) { finish(capture); return }
      const AudioCtx = window.AudioContext || (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      if (!AudioCtx) throw new Error('Audio recording is unavailable.')
      const audioCtx = new AudioCtx({ sampleRate: 16000 })
      capture.context = audioCtx
      const source = audioCtx.createMediaStreamSource(stream)
      capture.source = source
      const processor = audioCtx.createScriptProcessor(4096, 1, 1)
      capture.processor = processor
      processor.onaudioprocess = (e) => {
        if (!owns(capture) || !isRecording.value) return
        const inputData = e.inputBuffer.getChannelData(0)
        capture.chunks.push(new Float32Array(inputData))
      }
      source.connect(processor)
      processor.connect(audioCtx.destination)
      isRecording.value = true
      capture.startedAt = Date.now()
    } catch (err) {
      if (owns(capture)) console.error('Failed to start recording:', err)
      finish(capture)
    }
  }

  async function stopVoiceRecording() {
    const capture = current
    if (!capture || isTranscribing.value) return
    if (!isRecording.value) { cancelVoiceRecording(); return }
    isRecording.value = false
    releaseMedia(capture)
    clearMouseUpListener()
    if (!owns(capture) || Date.now() - capture.startedAt < 500) { finish(capture); return }

    const totalLength = capture.chunks.reduce((acc, chunk) => acc + chunk.length, 0)
    const flattened = new Float32Array(totalLength)
    let offset = 0
    for (const chunk of capture.chunks) {
      flattened.set(chunk, offset)
      offset += chunk.length
    }
    capture.chunks = []
    const wavBuffer = bufferToWav(flattened, 16000)
    const audioBlob = new Blob([wavBuffer], { type: 'audio/wav' })
    const revision = draftRevision, draft = inputText.value.trim()
    isTranscribing.value = true
    try {
      const { api } = await import('@/composables/useApi')
      if (!owns(capture) || revision !== draftRevision) return
      const result = await api.transcribeAudio(audioBlob, capture.request.signal)
      if (!owns(capture) || revision !== draftRevision) return
      const text = result.text.trim()
      if (text) {
        const prefix = capture.prefixSay ? '/say ' : ''
        inputText.value = draft ? `${draft} ${prefix}${text}` : `${prefix}${text}`
        onSend()
      }
    } catch (err) {
      if (owns(capture) && !capture.request.signal.aborted) console.error('Failed to transcribe audio:', err)
    } finally {
      finish(capture)
    }
  }

  function handleMicButtonMousedown(e: MouseEvent | TouchEvent) {
    e.preventDefault()
    if (disposed || current || !canSendInput.value) return
    pttPrefixSay.value = (e as MouseEvent).shiftKey || false
    pttKeyActiveCode.value = ''
    void startVoiceRecording()

    globalMouseUpListener = () => {
      void stopVoiceRecording()
      clearMouseUpListener()
    }
    window.addEventListener('mouseup', globalMouseUpListener)
    window.addEventListener('touchend', globalMouseUpListener)
  }

  function handleGlobalKeydown(e: KeyboardEvent) {
    if (e.ctrlKey || e.metaKey || e.altKey || e.repeat) return
    const target = e.target as HTMLElement
    const isTyping = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable

    const isV = e.code === 'KeyV'
    const isB = e.code === 'KeyB'
    const isT = e.code === 'KeyT'
    if ((isV || isB || isT) && !isTyping && canSendInput.value) {
      e.preventDefault()
      if (!pttKeyPressed.value && !current && !disposed) {
        pttKeyPressed.value = true
        pttKeyActiveCode.value = e.code
        pttPrefixSay.value = isB || isT || e.shiftKey
        void startVoiceRecording()
      }
    }
  }

  function handleGlobalKeyup(e: KeyboardEvent) {
    const activeCode = pttKeyActiveCode.value || 'KeyV'
    if (e.code === activeCode && pttKeyPressed.value) {
      e.preventDefault()
      pttKeyPressed.value = false
      pttKeyActiveCode.value = ''
      void stopVoiceRecording()
    }
  }

  onMounted(() => {
    window.addEventListener('keydown', handleGlobalKeydown, { capture: true })
    window.addEventListener('keyup', handleGlobalKeyup)
    window.addEventListener('blur', cancelVoiceRecording)
  })

  watch(sessionId, cancelVoiceRecording, { flush: 'sync' })
  watch(canSendInput, available => { if (!available) cancelVoiceRecording() }, { flush: 'sync' })
  watch(inputText, () => { draftRevision++ }, { flush: 'sync' })
  onBeforeUnmount(() => {
    disposed = true
    cancelVoiceRecording()
    window.removeEventListener('keydown', handleGlobalKeydown, { capture: true })
    window.removeEventListener('keyup', handleGlobalKeyup)
    window.removeEventListener('blur', cancelVoiceRecording)
  })

  return {
    isRecording,
    isTranscribing,
    startVoiceRecording,
    stopVoiceRecording,
    handleMicButtonMousedown,
  }
}
