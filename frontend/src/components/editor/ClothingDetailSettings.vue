<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
  modelValue: boolean
  savedValue: boolean
  isSaving: boolean
  nsfwEnabled: boolean
  nsfwSavedEnabled: boolean
  nsfwLevel: 'soft' | 'medium' | 'hard'
  nsfwSavedLevel: 'soft' | 'medium' | 'hard'
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'update:nsfwEnabled': [value: boolean]
  'update:nsfwLevel': [value: 'soft' | 'medium' | 'hard']
  save: []
}>()

const showNsfwGate = ref(false)
const nsfwGateInput = ref('')
const nsfwGateError = ref(false)

function attemptNsfwEnable() {
  if (nsfwGateInput.value.trim() === 'NSFW') {
    emit('update:nsfwEnabled', true)
    showNsfwGate.value = false
    nsfwGateInput.value = ''
    nsfwGateError.value = false
  } else {
    nsfwGateError.value = true
  }
}

function openNsfwGate() {
  nsfwGateInput.value = ''
  nsfwGateError.value = false
  showNsfwGate.value = true
}

const hasChanges = computed(
  () =>
    props.modelValue !== props.savedValue ||
    props.nsfwEnabled !== props.nsfwSavedEnabled ||
    (props.nsfwEnabled && props.nsfwLevel !== props.nsfwSavedLevel)
)
</script>

<template>
  <section class="rounded-2xl border border-pink-400/20 bg-slate-950/30 p-5 space-y-5">
    <!-- Clothing layer -->
    <label class="flex items-start gap-3 text-sm">
      <input
        type="checkbox"
        :checked="modelValue"
        :disabled="isSaving"
        class="mt-1 h-4 w-4 shrink-0 accent-pink-400"
        @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
      />
      <span>
        <span class="font-semibold text-pink-300">Clothing layer tracking</span>
        <span class="mt-2 block text-xs leading-relaxed text-slate-400">
          Track clothing layers, including underlayers, for clearly adult characters. Save to
          prepare missing appearance and clothing fields from known character details and owned
          items. Preparation uses your Utility model and can take a few minutes.
        </span>
      </span>
    </label>

    <!-- NSFW -->
    <div class="border-t border-pink-400/10 pt-4">
      <label class="flex items-start gap-3 text-sm">
        <input
          type="checkbox"
          :checked="nsfwEnabled"
          :disabled="isSaving"
          class="mt-1 h-4 w-4 shrink-0 accent-pink-400"
          @change="
            ($event.target as HTMLInputElement).checked ? openNsfwGate() : emit('update:nsfwEnabled', false)
          "
        />
        <span>
          <span class="font-semibold text-pink-300">NSFW content</span>
          <span class="mt-2 block text-xs leading-relaxed text-slate-400">
            Allow explicit narrative and visual content. The level controls how direct the
            language and imagery become.
          </span>
        </span>
      </label>

      <!-- Level selector (visible when NSFW enabled) -->
      <div v-if="nsfwEnabled" role="group" aria-label="Content level"
        class="mt-3 ml-7 flex rounded-2xl border border-white/5 bg-black/40 p-1 shadow-inner">
        <button
          v-for="level in (['soft', 'medium', 'hard'] as const)"
          :key="level"
          type="button"
          :disabled="isSaving"
          :class="[
            'flex-1 rounded-xl px-3 py-3 text-xs font-black uppercase tracking-widest transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-pink-400 disabled:cursor-not-allowed disabled:opacity-50',
            nsfwLevel === level
              ? 'bg-pink-600 text-white shadow-lg'
              : 'text-slate-500 hover:text-slate-300'
          ]"
          :aria-pressed="nsfwLevel === level"
          @click="emit('update:nsfwLevel', level)"
        >
          {{ level }}
        </button>
      </div>
    </div>

    <!-- Save -->
    <div class="flex flex-wrap items-center gap-3">
      <button
        type="button"
        :disabled="isSaving || !hasChanges"
        class="rounded-xl bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
        @click="emit('save')"
      >
        {{ isSaving ? 'Saving settings…' : 'Save settings' }}
      </button>
      <span class="text-xs text-slate-400" role="status" aria-live="polite">
        {{ hasChanges ? 'Unsaved changes' : 'Saved' }}
      </span>
    </div>

    <!-- NSFW password gate modal -->
    <Teleport to="body">
      <div
        v-if="showNsfwGate"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
        @click.self="showNsfwGate = false"
      >
        <div class="w-80 rounded-2xl border border-pink-400/30 bg-slate-950 p-6 shadow-2xl">
          <h3 class="text-sm font-black text-pink-300 uppercase tracking-widest">Enable NSFW</h3>
          <p class="mt-2 text-xs text-slate-400">
            Type <code class="text-pink-300">NSFW</code> to confirm.
          </p>
          <input
            v-model="nsfwGateInput"
            type="text"
            class="mt-3 w-full rounded-xl border border-slate-700 bg-black/60 px-4 py-2 text-sm text-slate-200 outline-none focus:border-pink-400/50"
            placeholder="NSFW"
            @keyup.enter="attemptNsfwEnable"
          />
          <p v-if="nsfwGateError" class="mt-2 text-xs text-red-400">
            Incorrect. Type exactly <code class="text-red-300">NSFW</code>.
          </p>
          <div class="mt-4 flex gap-3">
            <button
              type="button"
              class="flex-1 rounded-xl bg-pink-600 px-4 py-2 text-xs font-bold text-white hover:bg-pink-500"
              @click="attemptNsfwEnable"
            >
              Confirm
            </button>
            <button
              type="button"
              class="flex-1 rounded-xl bg-slate-800 px-4 py-2 text-xs font-bold text-slate-400 hover:text-slate-200"
              @click="showNsfwGate = false"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>
