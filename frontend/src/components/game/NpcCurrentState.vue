<script setup lang="ts">
import type { NpcCurrentState } from '@/types/npcCurrentState'
import NpcClothingTile from './NpcClothingTile.vue'

defineProps<{ state?: NpcCurrentState }>()
const kinds = {
  injury: 'Injury',
  contamination: 'Contamination',
  fluid: 'Fluid',
  pain: 'Pain',
  other: 'Physical condition'
}
const statuses = { active: 'Active', treated: 'Treated', reduced: 'Reduced' }
</script>

<template>
  <section aria-label="Current clothing and physical condition" class="space-y-4">
    <p v-if="!state" class="rounded-xl border border-slate-700 p-4 text-slate-400">
      Current observations are not available yet.
    </p>
    <p
      v-else-if="state.availability !== 'present'"
      class="rounded-xl border border-slate-700 p-4 text-slate-400"
    >
      This character is not currently visible here. Their present clothing and physical condition
      are not available.
    </p>
    <template v-else>
      <p class="text-xs leading-relaxed text-slate-400">
        Current observations · game minute {{ state.game_minute }}. Covered clothing and private
        conditions stay hidden.
      </p>
      <div class="grid items-start gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <section class="min-w-0" aria-label="Visible clothing">
          <h3 class="font-semibold text-slate-100">
            Visible clothing
            <span class="ml-1 text-xs text-slate-400">{{ state.clothing.items.length }}</span>
          </h3>
          <p v-if="state.clothing.status === 'unavailable'" class="mt-3 text-slate-400">
            Clothing details are not confirmed.
          </p>
          <template v-else>
            <p v-if="state.clothing.detail_limited" class="mt-2 text-xs text-amber-200">
              Some clothing details are unspecified.
            </p>
            <ul v-if="state.clothing.items.length" class="mt-3 grid grid-cols-2 gap-3">
              <NpcClothingTile
                v-for="item in state.clothing.items"
                :key="item.item_id"
                :item="item"
              />
            </ul>
            <p v-else class="mt-3 text-slate-400">
              No visible garments recorded. This does not establish undress.
            </p>
          </template>
        </section>
        <section class="min-w-0" aria-label="Known physical conditions">
          <h3 class="font-semibold text-slate-100">Physical condition</h3>
          <p v-if="state.conditions.status === 'unavailable'" class="mt-3 text-slate-400">
            Current physical conditions are not confirmed.
          </p>
          <ul v-else-if="state.conditions.items.length" class="mt-3 space-y-3">
            <li
              v-for="condition in state.conditions.items"
              :key="condition.id"
              class="rounded-xl border border-rose-400/20 bg-rose-400/5 p-3"
            >
              <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span class="font-semibold text-rose-200"
                  >{{ kinds[condition.kind] }} · {{ condition.part }}</span
                >
                <span class="rounded bg-slate-950/60 px-2 py-1 text-slate-300">{{
                  statuses[condition.status]
                }}</span>
              </div>
              <p v-if="condition.target_name" class="mt-2 text-xs text-slate-400">
                {{ condition.target_name }}
              </p>
              <p class="mt-2 whitespace-pre-wrap break-words leading-relaxed text-slate-200">
                {{ condition.detail }}
              </p>
              <p class="mt-2 text-xs text-slate-400">
                {{
                  condition.observation === 'recorded'
                    ? 'Previously confirmed in the story · not currently visible'
                    : 'Visible now'
                }}
              </p>
              <p v-if="condition.last_changed_minute != null" class="mt-2 text-xs text-slate-500">
                Updated at game minute {{ condition.last_changed_minute }}
              </p>
            </li>
          </ul>
          <p v-else class="mt-3 text-slate-400">No known physical conditions recorded.</p>
        </section>
      </div>
    </template>
  </section>
</template>
