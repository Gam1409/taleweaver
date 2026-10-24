<script setup lang="ts">
import { computed } from 'vue'
import { ShieldAlert, ShieldCheck, ShieldX } from 'lucide-vue-next'

export interface ValidationLoggedFinding {
  severity: 'error' | 'warn'
  message: string
  location?: string | null
}

export interface ValidationLogDetails {
  failed?: boolean
  findings_total?: number
  errors?: number
  warnings?: number
  fixed?: number
  remaining?: number
  ai_skipped_reason?: string | null
  fixed_findings?: ValidationLoggedFinding[]
  open_findings?: ValidationLoggedFinding[]
}

const props = defineProps<{
  content: string
  details?: ValidationLogDetails
}>()

type Tone = 'clean' | 'open' | 'failed'

const tone = computed<Tone>(() => {
  if (props.details?.failed) return 'failed'
  return props.details?.ai_skipped_reason || (props.details?.remaining ?? 0) > 0 ? 'open' : 'clean'
})

const toneStyles: Record<Tone, { box: string; title: string; label: string; icon: typeof ShieldCheck }> = {
  clean: { box: 'border-emerald-500/25 bg-emerald-500/5', title: 'text-emerald-400', label: 'Validation & Auto-fix Complete', icon: ShieldCheck },
  open: { box: 'border-amber-500/25 bg-amber-500/5', title: 'text-amber-400', label: 'Validation Results', icon: ShieldAlert },
  failed: { box: 'border-rose-500/25 bg-rose-500/5', title: 'text-rose-400', label: 'Validation Incomplete', icon: ShieldX },
}

const style = computed(() => toneStyles[tone.value])

// Each section lists a few findings; the badge marks fixed vs. still-open issues.
const sections = computed(() => {
  const d = props.details
  if (!d) return []
  const fixed = d.fixed_findings ?? []
  const open = d.open_findings ?? []
  return [
    { key: 'fixed', label: 'Fixed', badge: 'text-emerald-400 border-emerald-500/40', items: fixed, hidden: Math.max(0, (d.fixed ?? 0) - fixed.length) },
    { key: 'open', label: 'Open', badge: 'text-amber-400 border-amber-500/40', items: open, hidden: Math.max(0, (d.remaining ?? 0) - open.length) },
  ].filter((section) => section.items.length > 0)
})
</script>

<template>
  <div class="flex justify-center w-full max-w-[95%] sm:max-w-[90%] self-center my-1 animate-fade-in">
    <div :class="['rounded-2xl border p-3.5 sm:p-4 flex flex-col gap-2 w-full', style.box]">
      <div :class="['flex items-center justify-center gap-2 text-xs font-black uppercase tracking-widest', style.title]">
        <component :is="style.icon" class="w-4 h-4 shrink-0" />
        <span>{{ style.label }}</span>
      </div>
      <p class="text-xs text-slate-300 text-center">{{ props.content }}</p>

      <ul v-if="sections.length" class="flex flex-col gap-1 mt-1">
        <template v-for="section in sections" :key="section.key">
          <li
            v-for="(finding, idx) in section.items"
            :key="section.key + idx"
            class="flex items-start gap-2 text-[11px] leading-snug text-slate-400 bg-black/30 rounded-lg px-2.5 py-1.5 border border-white/5"
          >
            <span :class="['shrink-0 mt-0.5 px-1.5 rounded text-[9px] font-black uppercase tracking-wider border', section.badge]">
              {{ section.label }}
            </span>
            <span class="break-words">{{ finding.message }}</span>
          </li>
          <li v-if="section.hidden > 0" class="text-[10px] text-slate-500 text-center">
            +{{ section.hidden }} more {{ section.label.toLowerCase() }}
          </li>
        </template>
      </ul>

      <p v-if="(props.details?.remaining ?? 0) > 0" class="text-[10px] text-slate-500 text-center">
        Details in the editor's Validation tab
      </p>
      <p v-if="props.details?.ai_skipped_reason" class="text-[10px] text-slate-500 text-center italic">
        AI check skipped: {{ props.details.ai_skipped_reason }}
      </p>
    </div>
  </div>
</template>
