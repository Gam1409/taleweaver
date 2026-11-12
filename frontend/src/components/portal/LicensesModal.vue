<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { FileText, X } from 'lucide-vue-next'
import { LICENSE_CATALOG } from '@/utils/licenseCatalog'

const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>()
const content = ref<HTMLElement>()
const selectedId = ref('application')
const selected = computed(() => LICENSE_CATALOG.find(item => item.id === selectedId.value)!)
const groups = [...new Set(LICENSE_CATALOG.map(item => item.group))]
const text = ref(''), error = ref(''), loading = ref(false)
const cache = new Map<string, string>()
let request: AbortController | undefined

async function load() {
  request?.abort()
  const current = new AbortController()
  request = current
  const entry = selected.value
  text.value = ''
  error.value = ''
  loading.value = true
  try {
    const cached = cache.get(entry.id)
    const response = cached === undefined ? await fetch(entry.url, { signal: current.signal }) : null
    if (response && !response.ok) throw new Error('License unavailable')
    const value = cached ?? await response!.text()
    if (request !== current) return
    cache.set(entry.id, value)
    text.value = value
    await nextTick()
    content.value?.scrollTo({ top: 0 })
  } catch {
    if (!current.signal.aborted) error.value = 'Could not load this license. Please try again.'
  } finally {
    if (request === current) loading.value = false
  }
}
watch(selectedId, load)
onMounted(() => { dialog.value?.showModal(); void load() })
onBeforeUnmount(() => { request?.abort(); dialog.value?.close() })
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="licenses-modal font-ui" aria-labelledby="licenses-title" @close="emit('close')">
      <div class="licenses-shell">
        <header class="flex shrink-0 items-start justify-between gap-4 border-b border-slate-700/60 p-5 sm:p-6">
          <div>
            <h2 id="licenses-title" class="flex items-center gap-2 text-xl font-semibold text-slate-100"><FileText class="h-5 w-5 text-amber-200/80" aria-hidden="true" />Licenses</h2>
            <p class="mt-1 text-sm text-slate-400">Original development: Jean Schmitz · Fork creator: Anton Kuprin</p>
          </div>
          <button type="button" class="rounded-lg border border-slate-700 p-2 text-slate-300 hover:bg-slate-800" aria-label="Close licenses" @click="dialog?.close()"><X class="h-4 w-4" aria-hidden="true" /></button>
        </header>
        <div class="shrink-0 border-b border-slate-700/60 p-5 sm:px-6">
          <label for="license-document" class="mb-2 block text-sm text-slate-400">License document</label>
          <select id="license-document" v-model="selectedId" class="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-200">
            <optgroup v-for="group in groups" :key="group" :label="group">
              <option v-for="entry in LICENSE_CATALOG.filter(item => item.group === group)" :key="entry.id" :value="entry.id">{{ entry.label }} — {{ entry.license }}</option>
            </optgroup>
          </select>
        </div>
        <section ref="content" tabindex="0" class="licenses-content min-h-0 flex-1 overflow-y-auto overscroll-contain p-5 sm:p-6" aria-label="License text" :aria-busy="loading">
          <p v-if="loading" role="status" class="text-sm text-slate-400">Loading license…</p>
          <div v-else-if="error" role="alert" class="text-sm text-rose-200">{{ error }} <button type="button" class="ml-2 underline" @click="load">Retry</button></div>
          <pre v-else class="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-slate-300">{{ text }}</pre>
        </section>
        <footer class="flex shrink-0 items-center justify-between gap-4 border-t border-slate-700/60 p-4 sm:px-6">
          <a :href="selected.url" download class="text-sm text-amber-200 hover:underline">Download text</a>
          <button type="button" class="rounded-xl border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800" @click="dialog?.close()">Close</button>
        </footer>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
.licenses-modal { width: min(780px, calc(100vw - 24px)); max-height: calc(100dvh - 32px); padding: 0; border: 1px solid #334155; border-radius: 18px; color: #e2e8f0; background: #101827; box-shadow: 0 24px 90px #0009; }
.licenses-modal::backdrop { background: #02060cbb; backdrop-filter: blur(5px); }
.licenses-shell { display: flex; flex-direction: column; height: min(760px, calc(100dvh - 34px)); }
.licenses-content { scrollbar-width: thin; scrollbar-color: #475569 transparent; }
.licenses-modal :is(button, a, select, section):focus-visible { outline: 2px solid #d6b46f; outline-offset: 2px; }
</style>
