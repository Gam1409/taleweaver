<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronDown, ChevronRight, Plus, Save, Trash2 } from 'lucide-vue-next'
import type { SpecialAttack, SpecialEffect } from '@/types'
import { specialAttackService, type SpecialAttackOwner } from '@/services/specialAttackService'
import {
  AMOUNT_PATTERN,
  CATEGORY_META,
  EFFECT_STATS,
  SPECIAL_CATEGORIES,
  STAT_SHORT,
  SUCCESS_STATS,
  checkLabel,
  costLabel,
  describeEffects,
  normalizeSpecialAttack,
} from '@/utils/specialAttacks'

const MAX_ATTACKS = 8
const ID_PATTERN = /^[A-Z0-9_-]{1,128}$/

const props = defineProps<{
  adventureId: string
  targetType: SpecialAttackOwner
  targetId: string
  ownerName: string
  attacks: SpecialAttack[]
}>()

const emit = defineEmits<{
  saved: [attacks: SpecialAttack[]]
}>()

type Draft = SpecialAttack & { effects: SpecialEffect[]; _key: number }

let keyCounter = 0
const drafts = ref<Draft[]>([])
const expanded = ref<number | null>(null)
const saving = ref(false)
const error = ref('')
const savedNote = ref('')

const PRESETS: Record<string, Omit<SpecialAttack, 'id'>> = {
  Fireball: {
    name: 'Fireball', description: 'A roaring ball of flame.', action_type: 'ATTACK', category: 'MAGIC',
    cost_type: 'mana', cost: 25, effects: [{ target: 'target', stat: 'hp', amount: '-3d6' }],
  },
  'Shield Bash': {
    name: 'Shield Bash', description: 'Slams the shield into the foe, leaving it dazed.', action_type: 'ATTACK',
    category: 'MELEE', cost_type: 'stamina', cost: 20,
    effects: [{ target: 'target', stat: 'hp', amount: '-1d6' }, { target: 'target', stat: 'dexterity', amount: '-2' }],
  },
  Insult: {
    name: 'Withering Insult', description: 'Words sharper than any blade.', action_type: 'UTILITY', category: 'SOCIAL',
    cost_type: 'stamina', cost: 10, success_stat: 'charisma',
    effects: [{ target: 'target', stat: 'charisma', amount: '-3' }, { target: 'target', stat: 'hp', amount: '-2' }],
  },
  'Battle Cry': {
    name: 'Battle Cry', description: 'A roar that steels the body.', action_type: 'UTILITY', category: 'OTHER',
    cost_type: 'stamina', cost: 15,
    effects: [{ target: 'self', stat: 'strength', amount: '+2' }, { target: 'self', stat: 'armor_class', amount: '+1' }],
  },
  Heal: {
    name: 'Mend Wounds', description: 'Soothing light closes wounds.', action_type: 'HEAL', category: 'MAGIC',
    cost_type: 'mana', cost: 15, effects: [{ target: 'self', stat: 'hp', amount: '+2d8' }],
  },
}

function toDraft(attack: SpecialAttack): Draft {
  const normalized = normalizeSpecialAttack(attack)
  return { ...attack, ...normalized, effects: normalized.effects.map((e) => ({ ...e })), _key: ++keyCounter }
}

// Keyed by content so parents may pass freshly built arrays without wiping unsaved edits.
watch(() => `${props.targetId}:${JSON.stringify(props.attacks ?? [])}`, () => {
  drafts.value = (props.attacks ?? []).map(toDraft)
  expanded.value = null
}, { immediate: true })

function slugify(name: string): string {
  return name.toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 60) || 'SPECIAL'
}

function uniqueId(base: string): string {
  const taken = new Set(drafts.value.map((d) => d.id))
  let candidate = base
  for (let n = 2; taken.has(candidate); n += 1) candidate = `${base}_${n}`
  return candidate
}

function addAttack(presetName?: string): void {
  if (drafts.value.length >= MAX_ATTACKS) return
  const preset = presetName ? PRESETS[presetName] : null
  const base: SpecialAttack = preset
    ? { ...preset, effects: preset.effects?.map((e) => ({ ...e })), id: '' }
    : { id: '', name: 'New Attack', action_type: 'ATTACK', category: 'MELEE', cost_type: 'stamina', cost: 10, effects: [{ target: 'target', stat: 'hp', amount: '-1d6' }] }
  base.id = uniqueId(slugify(base.name))
  drafts.value.push(toDraft(base))
  expanded.value = drafts.value[drafts.value.length - 1]._key
}

function removeAttack(key: number): void {
  drafts.value = drafts.value.filter((d) => d._key !== key)
}

function addEffect(draft: Draft): void {
  draft.effects.push({ target: 'target', stat: 'hp', amount: '-1d4' })
}

const problems = computed(() => {
  const issues: string[] = []
  const ids = new Set<string>()
  for (const d of drafts.value) {
    if (!d.name.trim()) issues.push('Every attack needs a name.')
    if (!ID_PATTERN.test(d.id)) issues.push(`"${d.name}": ID may only use A-Z, 0-9, _ and -.`)
    if (ids.has(d.id)) issues.push(`Duplicate ID ${d.id}.`)
    ids.add(d.id)
    if (d.effects.some((e) => !AMOUNT_PATTERN.test(e.amount.replace(/\s/g, '')))) {
      issues.push(`"${d.name}": amounts must look like -2d6, +5 or -3.`)
    }
  }
  return issues
})

function serialize(d: Draft): SpecialAttack {
  const rest: Partial<Draft> = { ...d }
  delete rest._key
  delete rest.damage_type
  delete rest.damage_value
  const cost = Math.max(0, Number(d.cost) || 0)
  return {
    ...(rest as SpecialAttack),
    id: d.id.trim().toUpperCase(),
    name: d.name.trim(),
    description: d.description ?? '',
    cost,
    mana_cost: d.cost_type === 'mana' ? cost : 0,
    difficulty: d.difficulty ? Number(d.difficulty) : null,
    effects: d.effects.map((e) => ({ ...e, amount: e.amount.replace(/\s/g, '') })),
  }
}

async function save(): Promise<void> {
  if (problems.value.length) return
  saving.value = true
  error.value = ''
  savedNote.value = ''
  try {
    const saved = await specialAttackService.save(props.adventureId, props.targetType, props.targetId, drafts.value.map(serialize))
    savedNote.value = 'Saved.'
    emit('saved', saved)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to save.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h4 class="text-xs font-black text-slate-500 uppercase tracking-[0.2em]">Special Attacks · {{ ownerName }}</h4>
      <div class="flex flex-wrap items-center gap-1.5">
        <span class="text-[10px] text-slate-500 uppercase tracking-widest mr-1">Add</span>
        <button
          v-for="name in Object.keys(PRESETS)"
          :key="name"
          type="button"
          class="px-2 py-1 rounded-lg border border-white/10 bg-slate-800/60 text-[11px] font-bold text-slate-300 hover:border-emerald-400/50 hover:text-white disabled:opacity-40"
          :disabled="drafts.length >= MAX_ATTACKS"
          @click="addAttack(name)"
        >{{ name }}</button>
        <button
          type="button"
          class="px-2 py-1 rounded-lg border border-emerald-500/40 bg-emerald-950/40 text-[11px] font-bold text-emerald-300 flex items-center gap-1 disabled:opacity-40"
          :disabled="drafts.length >= MAX_ATTACKS"
          @click="addAttack()"
        ><Plus class="w-3 h-3" /> Blank</button>
      </div>
    </div>

    <p v-if="!drafts.length" class="text-xs text-slate-500 italic">No special attacks yet. Add a preset or start from scratch.</p>

    <article v-for="d in drafts" :key="d._key" class="rounded-xl border border-white/10 bg-slate-950/40">
      <header class="flex items-center gap-2 px-3 py-2 cursor-pointer" @click="expanded = expanded === d._key ? null : d._key">
        <component :is="expanded === d._key ? ChevronDown : ChevronRight" class="w-4 h-4 text-slate-500" />
        <i :class="['ra text-base text-slate-300', CATEGORY_META[normalizeSpecialAttack(d).category].icon]"></i>
        <span class="font-bold text-sm text-white truncate">{{ d.name || 'Unnamed' }}</span>
        <span class="text-[10px] font-mono text-slate-400 truncate">
          {{ costLabel(normalizeSpecialAttack(d)) }} · {{ checkLabel(normalizeSpecialAttack(d)) }} · {{ describeEffects(d.effects) || 'no effects' }}
        </span>
        <button type="button" class="ml-auto p-1 text-slate-500 hover:text-rose-400" title="Remove attack" @click.stop="removeAttack(d._key)">
          <Trash2 class="w-4 h-4" />
        </button>
      </header>

      <div v-if="expanded === d._key" class="grid grid-cols-1 md:grid-cols-2 gap-3 px-3 pb-3 text-xs">
        <label class="space-y-1">
          <span class="text-slate-400 font-bold">Name</span>
          <input v-model="d.name" class="w-full bg-slate-900 border border-white/10 rounded-lg px-2 py-1.5 text-white" />
        </label>
        <label class="space-y-1">
          <span class="text-slate-400 font-bold">ID</span>
          <input v-model="d.id" class="w-full bg-slate-900 border border-white/10 rounded-lg px-2 py-1.5 text-white font-mono uppercase" />
        </label>
        <label class="space-y-1 md:col-span-2">
          <span class="text-slate-400 font-bold">Description</span>
          <input v-model="d.description" class="w-full bg-slate-900 border border-white/10 rounded-lg px-2 py-1.5 text-white" />
        </label>
        <label class="space-y-1">
          <span class="text-slate-400 font-bold">Category</span>
          <select v-model="d.category" class="w-full bg-slate-900 border border-white/10 rounded-lg px-2 py-1.5 text-white">
            <option v-for="c in SPECIAL_CATEGORIES" :key="c" :value="c">{{ CATEGORY_META[c].label }}</option>
          </select>
        </label>
        <label class="space-y-1">
          <span class="text-slate-400 font-bold">Behaviour (NPC AI)</span>
          <select v-model="d.action_type" class="w-full bg-slate-900 border border-white/10 rounded-lg px-2 py-1.5 text-white">
            <option value="ATTACK">Attack</option>
            <option value="HEAL">Heal</option>
            <option value="UTILITY">Utility</option>
          </select>
        </label>
        <div class="flex gap-2">
          <label class="space-y-1 flex-1">
            <span class="text-slate-400 font-bold">Cost</span>
            <input v-model.number="d.cost" type="number" min="0" class="w-full bg-slate-900 border border-white/10 rounded-lg px-2 py-1.5 text-white" />
          </label>
          <label class="space-y-1 flex-1">
            <span class="text-slate-400 font-bold">Paid with</span>
            <select v-model="d.cost_type" class="w-full bg-slate-900 border border-white/10 rounded-lg px-2 py-1.5 text-white">
              <option value="mana">Mana</option>
              <option value="stamina">Stamina</option>
            </select>
          </label>
        </div>
        <div class="flex gap-2">
          <label class="space-y-1 flex-1">
            <span class="text-slate-400 font-bold">Success roll stat</span>
            <select v-model="d.success_stat" class="w-full bg-slate-900 border border-white/10 rounded-lg px-2 py-1.5 text-white">
              <option v-for="s in SUCCESS_STATS" :key="s" :value="s">{{ STAT_SHORT[s] }}</option>
            </select>
          </label>
          <label class="space-y-1 flex-1">
            <span class="text-slate-400 font-bold">Difficulty (DC)</span>
            <input v-model.number="d.difficulty" type="number" min="0" placeholder="Target AC" class="w-full bg-slate-900 border border-white/10 rounded-lg px-2 py-1.5 text-white" />
          </label>
        </div>

        <div class="md:col-span-2 space-y-1.5">
          <div class="flex items-center justify-between">
            <span class="text-slate-400 font-bold">Effects on success</span>
            <button type="button" class="text-emerald-400 font-bold flex items-center gap-1" @click="addEffect(d)"><Plus class="w-3 h-3" /> Effect</button>
          </div>
          <div v-for="(eff, idx) in d.effects" :key="idx" class="flex items-center gap-2">
            <select v-model="eff.target" class="bg-slate-900 border border-white/10 rounded-lg px-2 py-1 text-white">
              <option value="target">Target</option>
              <option value="self">Self</option>
            </select>
            <select v-model="eff.stat" class="bg-slate-900 border border-white/10 rounded-lg px-2 py-1 text-white">
              <option v-for="s in EFFECT_STATS" :key="s" :value="s">{{ STAT_SHORT[s] }}</option>
            </select>
            <input
              v-model="eff.amount"
              placeholder="-2d6"
              class="w-28 bg-slate-900 border rounded-lg px-2 py-1 text-white font-mono"
              :class="AMOUNT_PATTERN.test(eff.amount.replace(/\s/g, '')) ? 'border-white/10' : 'border-rose-500/70'"
            />
            <button type="button" class="p-1 text-slate-500 hover:text-rose-400" @click="d.effects.splice(idx, 1)"><Trash2 class="w-3.5 h-3.5" /></button>
          </div>
          <p class="text-[10px] text-slate-500">Negative amounts drain, positive amounts boost. HP/MP/STA change directly; attribute changes last until the fight ends.</p>
        </div>

        <label class="space-y-1 md:col-span-2">
          <span class="text-slate-400 font-bold">Outcome narration (optional)</span>
          <textarea v-model="d.outcome_description" rows="2" class="w-full bg-slate-900 border border-white/10 rounded-lg px-2 py-1.5 text-white"></textarea>
        </label>
        <div class="md:col-span-2 flex flex-wrap items-center gap-2">
          <label class="flex items-center gap-2 text-slate-300 font-bold">
            <input v-model="d.is_locked" type="checkbox" class="accent-emerald-500" /> Starts locked
          </label>
          <template v-if="d.is_locked">
            <select v-model="d.unlock_condition_type" class="bg-slate-900 border border-white/10 rounded-lg px-2 py-1 text-white">
              <option value="READ_ITEM">Unlocked by reading item</option>
              <option value="FIND_ITEM">Unlocked by finding item</option>
            </select>
            <input v-model="d.unlock_condition_target" placeholder="ITEM_ID" class="w-40 bg-slate-900 border border-white/10 rounded-lg px-2 py-1 text-white font-mono" />
          </template>
        </div>
      </div>
    </article>

    <div class="flex flex-wrap items-center gap-3">
      <button
        type="button"
        class="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-black uppercase tracking-wider flex items-center gap-2 disabled:opacity-40"
        :disabled="saving || problems.length > 0"
        @click="save"
      >
        <Save class="w-3.5 h-3.5" /> {{ saving ? 'Saving…' : 'Save Special Attacks' }}
      </button>
      <span v-if="savedNote" class="text-xs text-emerald-400">{{ savedNote }}</span>
      <span v-if="error" class="text-xs text-rose-400">{{ error }}</span>
      <span v-for="p in problems" :key="p" class="text-xs text-amber-400">{{ p }}</span>
    </div>
  </section>
</template>
