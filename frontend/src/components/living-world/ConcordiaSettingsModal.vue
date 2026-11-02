<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { X, Globe2, Check } from 'lucide-vue-next'
import { apiFetch } from '@/services/http'
import type { LivingWorldPreferences } from '@/services/livingWorld'
import SettingHelp from './SettingHelp.vue'
import { concordiaDefaults, groups } from './settingsFields'

const props = defineProps<{ modelValue?: LivingWorldPreferences | null; existing?: boolean }>()
const emit = defineEmits<{ close: []; apply: [settings: LivingWorldPreferences] }>()
const draft = ref({ ...concordiaDefaults(), ...props.modelValue })
const original = JSON.stringify(draft.value)
const dirty = computed(() => JSON.stringify(draft.value) !== original)
const enabled = computed(() => draft.value.living_world_enabled && draft.value.deliberation_enabled && draft.value.decision_engine === 'concordia')
const dialog = ref<HTMLElement | null>(null)
const capability = ref<{ concordia_available: boolean; inference_serialization_enabled: boolean } | null>(null)
const capabilityError = ref(false)
let previousFocus: HTMLElement | null = null
let previousOverflow = ''
let disposed = false
function toggle(event: Event): void {
  const checked = (event.target as HTMLInputElement).checked
  draft.value = { ...draft.value, living_world_enabled: checked, deliberation_enabled: checked, decision_engine: 'concordia' }
}
function trap(event: KeyboardEvent): void {
  if (event.key !== 'Tab') return
  const nodes = dialog.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]')
  if (!nodes?.length) return
  const first = nodes[0], last = nodes[nodes.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
onMounted(async () => {
  previousFocus = document.activeElement as HTMLElement | null
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  await nextTick()
  dialog.value?.querySelector<HTMLInputElement>('input')?.focus()
  try {
    const response = await apiFetch('/adventures/living-world/capabilities')
    if (!response.ok) throw new Error('Unavailable')
    const value = await response.json()
    if (!disposed) capability.value = value
  } catch { if (!disposed) capabilityError.value = true }
})
onBeforeUnmount(() => { disposed = true; document.body.style.overflow = previousOverflow; previousFocus?.focus() })
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-3 backdrop-blur-sm sm:p-6" @click.self="emit('close')">
      <section ref="dialog" role="dialog" aria-modal="true" aria-labelledby="concordia-title" class="flex max-h-[90dvh] w-full max-w-3xl flex-col overflow-hidden rounded-3xl border border-white/10 bg-slate-950 shadow-2xl" @keydown="trap" @keydown.esc="emit('close')">
        <header class="flex items-center justify-between border-b border-white/10 px-5 py-4 sm:px-7">
          <div class="flex items-center gap-3"><Globe2 class="h-6 w-6 text-cyan-400" /><div><h2 id="concordia-title" class="text-lg font-black text-white">Living World</h2><p class="text-[10px] font-bold uppercase tracking-[0.2em] text-cyan-300/70">Concordia · Experimental</p></div></div>
          <button type="button" aria-label="Close Living World" class="rounded-xl p-2 text-white/50 transition hover:bg-white/10 hover:text-white" @click="emit('close')"><X class="h-5 w-5" /></button>
        </header>
        <div class="space-y-6 overflow-y-auto p-5 sm:p-7">
          <div class="flex items-center justify-between gap-3 rounded-2xl border p-4 transition" :class="enabled ? 'border-cyan-400/40 bg-cyan-400/10' : 'border-white/10 bg-white/5'">
            <label class="flex cursor-pointer items-center gap-3 text-sm font-bold text-white"><input type="checkbox" :checked="enabled" class="h-5 w-5 accent-cyan-400" @change="toggle"> Enable Concordia</label>
            <SettingHelp label="Enable Concordia" text="Enables Living World and private NPC decisions using the Concordia engine. Disabling it stops this feature for new sessions created from this adventure. Existing sessions keep their saved settings." />
          </div>
          <p v-if="!enabled" class="text-sm leading-relaxed text-white/50">Enable Concordia to configure NPC routines, private decisions and activity while you are away.</p>
          <template v-else>
            <p v-if="capabilityError || (capability && (!capability.concordia_available || !capability.inference_serialization_enabled))" role="status" class="rounded-xl border border-amber-400/20 bg-amber-400/5 p-3 text-xs leading-relaxed text-amber-200">
              <template v-if="capabilityError">Server prerequisites could not be checked. You can save the configuration and verify the server before playing.</template>
              <template v-else>Before running Concordia, the server needs the optional Concordia 2.4 package (Python 3.12/3.13) and shared inference serialization enabled. You can prepare these adventure settings now.</template>
            </p>
            <div class="space-y-3">
              <div class="flex items-center justify-between gap-3"><label class="flex items-center gap-3 text-sm text-white/80"><input v-model="draft.live_enabled" type="checkbox" class="h-4 w-4 accent-cyan-400"> Run automatically while playing</label><SettingHelp label="Automatic processing" text="Runs bounded background batches while this session is open. Game time still follows narration; reading a reply does not advance the scene. Stops starting batches when presence expires. Existing request budgets still apply." /></div>
              <div class="flex items-center justify-between gap-3"><label class="flex items-center gap-3 text-sm text-white/80"><input v-model="draft.allow_concurrent_requests" type="checkbox" class="h-4 w-4 accent-cyan-400"> Allow concurrent LLM requests</label><SettingHelp label="Concurrent LLM requests" text="Allows one Living World request alongside the normal request on the same AI endpoint (two total). Enable only when your model server supports parallel requests and has enough resources. World changes remain serialized and stale replies are discarded. Disabled: background decisions wait for an idle opportunity." /></div>
              <div class="flex items-center justify-between gap-3"><label class="flex items-center gap-3 text-sm text-white/80"><input v-model="draft.dialogue_choices_enabled" type="checkbox" class="h-4 w-4 accent-cyan-400"> NPC choices in important conversations</label><SettingHelp label="Conversation choices" text="Adds at most one Utility request before narration for a recognized request, offer, trust question, decision or wait/continue cue (English/Russian) with an unambiguous present NPC. Includes bounded recent dialogue. The NPC may respond, initiate a small next step or continue an established action; narration writes the reply and leaves player choices open. Uses the shared timeline request allowance and adds model latency. Ordinary chatter is skipped." /></div>
              <div class="flex items-center justify-between gap-3"><label class="block text-sm text-white/80">Automatic batch interval (seconds)<input v-model.number="draft.live_interval_seconds" type="number" min="20" max="600" class="ml-3 w-20 rounded-lg bg-slate-800 p-2"></label><SettingHelp label="Automatic batch interval" text="Minimum seconds between automatic batches (20–600). Presence is checked about every 20 seconds. Busy inference and long model responses can delay the next batch; this does not alter the LLM timeout or game clock." /></div>

              <div class="flex items-center justify-between"><span class="text-xs font-black uppercase tracking-widest text-white/60">While you are away</span><SettingHelp label="Offline mode" text="Pause keeps the game clock unchanged while you are away. Catch up converts absence into pending game time; only a bounded batch is processed at once, and the rest remains queued." /></div>
              <div class="grid grid-cols-2 gap-2" role="group" aria-label="Offline mode">
                <button v-for="option in ([{ value: 'PAUSE', label: 'Pause' }, { value: 'CATCH_UP', label: 'Catch up' }] as const)" :key="option.value" type="button" :aria-pressed="draft.mode === option.value" class="rounded-xl border px-4 py-3 text-xs font-black uppercase tracking-wider transition active:scale-95" :class="draft.mode === option.value ? 'border-cyan-400 bg-cyan-400/10 text-white' : 'border-white/10 bg-white/5 text-white/40 hover:text-white'" @click="draft.mode = option.value">{{ option.label }}</button>
              </div>
              <div class="flex items-center justify-between gap-3"><label class="flex items-center gap-3 text-sm text-white/80"><input v-model="draft.auto_catchup_on_resume" type="checkbox" class="h-4 w-4 accent-cyan-400"> Run one batch when returning</label><SettingHelp label="Automatic return batch" text="Runs one bounded batch when the session reconnects. It does not start an endless loop. Further backlog can be processed manually from session settings." /></div>
              <div class="flex items-center justify-between gap-3"><label class="flex items-center gap-3 text-sm text-white/80"><input v-model="draft.auto_schedule" type="checkbox" class="h-4 w-4 accent-cyan-400"> Recurring NPC routines</label><SettingHelp label="Recurring NPC routines" text="Automatically schedules small NPC decisions at the chosen interval. When disabled, only explicitly scheduled simulation events are processed." /></div>
            </div>
            <section v-for="group in groups" :key="group.title" class="space-y-4 border-t border-white/10 pt-5">
              <h3 class="text-xs font-black uppercase tracking-[0.2em] text-cyan-300/70">{{ group.title }}</h3>
              <div class="grid gap-4 sm:grid-cols-2">
                <div v-for="field in group.fields" :key="field.key" class="rounded-2xl border border-white/5 bg-white/[0.03] p-4">
                  <div class="mb-3 flex items-center justify-between gap-2"><label :for="`concordia-${field.key}`" class="text-xs font-bold text-white/80">{{ field.label }}</label><SettingHelp :label="field.label" :text="field.help" /></div>
                  <div class="flex items-center gap-3"><input :id="`concordia-${field.key}`" v-model.number="draft[field.key]" type="range" :min="field.min" :max="field.max" :step="field.step" class="h-1.5 min-w-0 flex-1 cursor-pointer accent-cyan-400"><output :for="`concordia-${field.key}`" class="min-w-16 rounded-lg bg-cyan-400/10 px-2 py-1 text-right text-xs font-bold tabular-nums text-cyan-200">{{ draft[field.key] }} {{ field.unit }}</output></div>
                </div>
              </div>
            </section>
            <div class="flex items-center justify-between gap-3 rounded-xl bg-white/5 p-3 text-xs text-white/50"><span>Uses your configured Utility model and its timeout.</span><SettingHelp label="Model, memory and timeout" text="Provider, model, URL, API key and request timeout come from Utility model settings. Each NPC keeps one short goal, one unverified belief and up to eight observations. These memory limits and the two-attempt retry limit are fixed safeguards, not adjustable options." /></div>
          </template>
        </div>
        <footer class="space-y-3 border-t border-white/10 px-5 py-4 sm:px-7">
          <p class="text-xs leading-relaxed text-white/50">{{ existing ? 'Changes apply to new sessions only. Already-started sessions keep their current Living World settings.' : 'These settings will be saved with the adventure and copied into its new VN sessions.' }}</p>
          <div class="flex justify-end gap-3"><button type="button" class="rounded-xl border border-white/10 px-5 py-2.5 text-xs font-bold text-white/60 transition hover:bg-white/5" @click="emit('close')">Cancel</button><button type="button" :disabled="!dirty" class="flex items-center gap-2 rounded-xl bg-cyan-400 px-5 py-2.5 text-xs font-black text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-30" @click="emit('apply', { ...draft })"><Check class="h-4 w-4" />{{ existing ? 'Save settings' : 'Apply settings' }}</button></div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
