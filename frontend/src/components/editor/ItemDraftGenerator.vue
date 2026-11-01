<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { generateItemDraft, type ItemDraft } from '@/services/itemGeneration'

const props = defineProps<{
  adventureId: string
  itemType: string
  fixedSlots: string[]
  disabled?: boolean
  contextVersion?: number
}>()
const emit = defineEmits<{
  (e: 'draft', value: ItemDraft): void
  (e: 'busy', value: boolean): void
}>()
const brief = ref('')
const busy = ref(false)
const error = ref('')
const generated = ref(false)
let revision = 0
function invalidate() {
  revision++
  busy.value = false
  error.value = ''
  generated.value = false
  emit('busy', false)
}
watch(() => JSON.stringify([props.adventureId, props.itemType, props.fixedSlots, props.contextVersion]), invalidate, { flush: 'sync' })
onBeforeUnmount(invalidate)

async function generate() {
  if (busy.value || props.disabled || !brief.value.trim()) return
  const requestRevision = ++revision
  busy.value = true
  error.value = ''
  generated.value = false
  emit('busy', true)
  try {
    const draft = await generateItemDraft(props.adventureId, brief.value.trim(), props.itemType, props.fixedSlots)
    if (requestRevision !== revision) return
    emit('draft', draft)
    generated.value = true
  } catch (cause) {
    if (requestRevision === revision) error.value = cause instanceof Error ? cause.message : 'Item generation failed.'
  } finally {
    if (requestRevision === revision) {
      busy.value = false
      emit('busy', false)
    }
  }
}
</script>

<template>
  <section class="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-4 space-y-3">
    <label class="block text-xs font-black uppercase tracking-widest text-emerald-400">
      Create from description
      <textarea v-model="brief" :disabled="busy || disabled" maxlength="2000" rows="3"
        class="mt-3 w-full rounded-xl border border-white/10 bg-black/30 p-3 text-sm font-normal normal-case tracking-normal text-slate-200 outline-none focus:border-emerald-500 resize-y"
        placeholder="A silver locket containing Miki's photograph. Worn around the neck. No magical properties."
      />
    </label>
    <p class="text-xs text-slate-400">Describe one item. The selected type ({{ itemType }}) is kept. Review the generated fields below, then click Create Object to save. Images are generated separately.</p>
    <button type="button" :disabled="busy || disabled || !brief.trim()" @click="generate"
      class="rounded-xl bg-emerald-600 px-4 py-2 text-xs font-black uppercase tracking-widest text-white hover:bg-emerald-500 disabled:opacity-50">
      {{ busy ? 'Generating draft...' : 'Generate item draft' }}
    </button>
    <p v-if="error" role="alert" class="text-sm text-red-300">{{ error }}</p>
    <p v-if="generated" role="status" class="text-sm text-emerald-300">Draft filled in below. Review its details before saving. Advanced rules and effects are configured manually.</p>
  </section>
</template>
