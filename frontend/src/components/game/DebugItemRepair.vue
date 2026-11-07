<script setup lang="ts">
import { nextTick, onScopeDispose, ref } from 'vue'
import { apiFetch } from '@/services/http'
import { getImageUrl } from '@/utils/game_icons'
import { Wrench } from 'lucide-vue-next'

const props = defineProps<{ sessionId: string; itemId: string; name?: string; stacked?: boolean }>()
const emit = defineEmits<{ repaired: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const baseline = ref('')
const draftName = ref('')
const description = ref('')
const technical = ref('{}')
const image = ref('')
const selected = ref<string[]>(['text'])
let controller: AbortController | null = null
const types = [
  'DEFAULT',
  'WEARABLE',
  'CONSUMABLE',
  'WEAPON',
  'READABLE',
  'COMBINABLE',
  'CONSTRUCTABLE',
  'CONTAINER',
  'SWITCH'
]
const endpoint = () =>
  `/adventures/${encodeURIComponent(props.sessionId)}/items/${encodeURIComponent(props.itemId)}/repair`
function fill(item: Record<string, unknown>) {
  draftName.value = String(item.name || props.name || props.itemId)
  description.value = String(item.description || '')
  technical.value = JSON.stringify(
    {
      item_type: types.includes(String(item.item_type)) ? item.item_type : 'DEFAULT',
      is_portable: item.is_portable !== false,
      wearable_slots: item.wearable_slots || [],
      clothing:
        item.clothing ||
        (item.metadata_json as Record<string, unknown> | undefined)?.clothing ||
        null
    },
    null,
    2
  )
}
async function request(action: string, body?: unknown) {
  if (busy.value) return null
  controller?.abort()
  const current = new AbortController()
  controller = current
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const response = await apiFetch(endpoint() + action, {
      method: body ? 'POST' : 'GET',
      signal: current.signal,
      timeoutMs: body && action !== '/apply' ? null : 15000,
      ...(body ? { includeJson: true, body: JSON.stringify(body) } : {})
    })
    const data = await response.json()
    if (!response.ok)
      throw new Error(
        typeof data.detail === 'string'
          ? data.detail
          : 'Item repair failed. Check the selected fields and server diagnostics.'
      )
    return controller === current ? data : null
  } catch (cause) {
    if (controller === current)
      error.value = cause instanceof Error ? cause.message : 'Item repair failed.'
    return null
  } finally {
    if (controller === current) busy.value = false
  }
}
async function open() {
  baseline.value = ''
  image.value = ''
  selected.value = ['text']
  await nextTick()
  dialog.value?.showModal()
  await load()
}
async function load() {
  const data = await request('')
  if (data) {
    baseline.value = data.before_hash
    image.value = ''
    selected.value = ['text']
    fill(data.item)
  }
}
async function reload() {
  if (busy.value) return
  if (baseline.value && !window.confirm('Reload the saved item? This discards the current repair draft and image preview.')) return
  await load()
}
async function generate() {
  const data = await request('/preview', {
    before_hash: baseline.value,
    instruction:
      'Develop the existing description into fluent, detailed literary prose. Repair inconsistent visual metadata without changing ownership or gameplay properties.'
  })
  if (data) {
    fill(data.values)
    notice.value =
      'Draft ready. Review the text and technical fields, then apply only the sections you want.'
  }
}
async function generateImage() {
  const data = await request('/image', { before_hash: baseline.value })
  if (data) {
    image.value = data.image_url
    if (!selected.value.includes('image')) selected.value.push('image')
    notice.value = 'Image preview ready; it has not replaced the saved image.'
  }
}
async function apply() {
  let values
  try {
    values = {
      ...(selected.value.includes('technical') ? JSON.parse(technical.value) : {}),
      name: draftName.value,
      description: description.value
    }
  } catch {
    error.value = 'Technical fields must be valid JSON. Fix the JSON before applying.'
    return
  }
  const data = await request('/apply', {
    before_hash: baseline.value,
    values,
    parts: selected.value,
    image_url: image.value || null
  })
  if (data) {
    baseline.value = data.before_hash
    fill(data.item)
    notice.value =
      'Selected sections saved. Ownership and unrelated properties were preserved.' +
      (data.replay_invalidated
        ? ' The last-turn replay point was reset to preserve this repair; play a new turn to create another.'
        : '')
    emit('repaired')
  }
}
function stop() {
  controller?.abort()
  controller = null
  busy.value = false
}
onScopeDispose(stop)
</script>

<template>
  <button
    type="button"
    :disabled="!sessionId"
    class="inline-flex items-center justify-center gap-1 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-cyan-300 hover:bg-cyan-500/20 disabled:opacity-40"
    :class="stacked ? 'w-full' : ''"
    :aria-label="`Repair ${props.name || itemId}`"
    @click="open"
  >
    <Wrench class="h-3 w-3" />Repair
  </button>
  <Teleport to="body"
    ><dialog
      ref="dialog"
      :aria-label="`Repair item — ${props.name || itemId}`"
      class="m-auto max-h-[90dvh] w-[min(64rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-slate-600 bg-slate-950 p-5 text-sm text-slate-200 shadow-xl backdrop:bg-black/80"
      @close="stop"
      @keydown.esc.stop
    >
      <header class="mb-5 flex items-center justify-between gap-4">
        <h2 class="text-lg font-bold">Repair item — {{ props.name || itemId }}</h2>
        <button type="button" class="rounded-lg bg-slate-800 px-3 py-2" @click="dialog?.close()">
          Close
        </button>
      </header>
      <p class="mb-4 text-xs text-slate-400">
        Session only. Generate a draft, edit it and choose what to apply. Model and image generation
        use configured providers and may incur cost. Image generation uses the currently saved
        description; apply text first to illustrate its updated appearance.
      </p>
      <p
        v-if="error"
        role="alert"
        class="mb-4 rounded-lg border border-rose-500/30 p-3 text-rose-300"
      >
        {{ error }}
      </p>
      <button
        v-if="error || baseline"
        type="button"
        :disabled="busy"
        class="mb-4 rounded-lg border border-cyan-600 px-3 py-2 text-xs text-cyan-200 disabled:opacity-40"
        @click="reload"
      >
        {{ baseline ? 'Reload saved item' : 'Retry loading item' }}
      </button>
      <p v-if="notice" role="status" class="mb-4 text-emerald-300">{{ notice }}</p>
      <fieldset :disabled="busy || !baseline" class="space-y-5 disabled:opacity-50">
        <div class="flex flex-wrap gap-3">
          <button
            type="button"
            class="rounded-lg bg-cyan-700 px-4 py-2 font-bold"
            @click="generate"
          >
            Generate text & technical draft</button
          ><button
            type="button"
            class="rounded-lg border border-cyan-600 px-4 py-2"
            @click="generateImage"
          >
            Generate image preview
          </button>
        </div>
        <div class="grid gap-5 md:grid-cols-2">
          <section class="min-w-0 space-y-3">
            <label class="flex items-center gap-2 font-bold"
              ><input v-model="selected" type="checkbox" value="text" /> Apply text</label
            ><label class="block text-xs"
              >Name<input
                v-model="draftName"
                maxlength="100"
                class="mt-1 w-full rounded-lg bg-slate-800 p-2" /></label
            ><label class="block text-xs"
              >Full description<textarea
                v-model="description"
                maxlength="1000"
                rows="10"
                class="mt-1 w-full rounded-lg bg-slate-800 p-3 leading-relaxed"
              />
            </label>
          </section>
          <section class="min-w-0 space-y-3">
            <label class="flex items-center gap-2 font-bold"
              ><input v-model="selected" type="checkbox" value="technical" /> Apply technical
              fields</label
            >
            <p class="text-xs text-slate-400">
              Type, portability, equipment slots and clothing layers. Existing scripts, bonuses,
              ownership and worn status stay unchanged.
            </p>
            <textarea
              v-model="technical"
              aria-label="Technical item JSON"
              rows="12"
              class="w-full rounded-lg bg-slate-800 p-3 font-mono text-xs"
            />
          </section>
        </div>
        <section v-if="image" class="space-y-3">
          <label class="flex items-center gap-2 font-bold"
            ><input v-model="selected" type="checkbox" value="image" /> Apply generated image</label
          ><img
            :src="getImageUrl(image)"
            alt="Generated item preview"
            class="h-52 w-52 rounded-xl border border-slate-600 object-contain"
          />
        </section>
        <button
          type="button"
          :disabled="!selected.length"
          class="rounded-lg bg-cyan-500 px-5 py-2 font-bold text-slate-950 disabled:opacity-40"
          @click="apply"
        >
          Apply selected sections
        </button>
      </fieldset>
      <p v-if="busy" role="status" class="mt-4 text-cyan-300">
        Working… The current saved item is kept until you apply a successful draft.
      </p>
    </dialog></Teleport
  >
</template>
