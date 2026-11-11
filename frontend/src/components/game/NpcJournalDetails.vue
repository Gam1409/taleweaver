<script setup lang="ts">
import { computed, onBeforeUnmount, ref, toRef, watch } from 'vue'
import { useNpcJournal, type NpcCard, type NpcHistoryKind } from '@/composables/useNpcJournal'
import { useNpcCardSettings } from '@/composables/useNpcCardSettings'
import NpcRelationship from './NpcRelationship.vue'
import NpcCardPreferences from './NpcCardPreferences.vue'
import NpcNarrativeInsights from './NpcNarrativeInsights.vue'
import NpcCurrentState from './NpcCurrentState.vue'

const props = defineProps<{ sessionId: string; npcId: string; stateRevision?: unknown }>()
const history = ref<NpcHistoryKind>('general')
const activeTab = ref<'state' | 'history'>('state')
const historyPanel = ref<HTMLElement | null>(null)
watch(
  history,
  () => {
    if (historyPanel.value) historyPanel.value.scrollTop = 0
  },
  { flush: 'post' }
)
watch(
  () => [props.sessionId, props.npcId],
  () => {
    history.value = 'general'
    activeTab.value = 'state'
  },
  { flush: 'sync' }
)
watch(
  activeTab,
  () => {
    if (historyPanel.value) historyPanel.value.scrollTop = 0
  },
  { flush: 'post' }
)
const settings = useNpcCardSettings(toRef(props, 'sessionId'))
const { details, loading, error, load } = useNpcJournal(
  toRef(props, 'sessionId'),
  toRef(props, 'npcId'),
  settings.showState,
  history
)
watch(
  () => props.stateRevision,
  () => { void load() }
)
const tabId = computed(
  () => `npc-history-${encodeURIComponent(props.sessionId)}-${encodeURIComponent(props.npcId)}`
)
function navigateSections(event: KeyboardEvent): void {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const selected =
    event.key === 'Home'
      ? 'state'
      : event.key === 'End'
        ? 'history'
        : activeTab.value === 'state'
          ? 'history'
          : 'state'
  activeTab.value = selected
  const container = (event.currentTarget as HTMLElement).closest('[role="tablist"]')
  container?.querySelector<HTMLButtonElement>(`[data-section="${selected}"]`)?.focus()
}
function navigateTabs(event: KeyboardEvent): void {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const selected =
    event.key === 'Home'
      ? 'general'
      : event.key === 'End'
        ? 'shared'
        : history.value === 'general'
          ? 'shared'
          : 'general'
  history.value = selected
  const container = (event.currentTarget as HTMLElement).closest('[role="tablist"]')
  container?.querySelector<HTMLButtonElement>(`[data-history="${selected}"]`)?.focus()
}
const emit = defineEmits<{ loaded: [card: NpcCard] }>()
watch(details, card => {
  if (card) emit('loaded', card)
})
const timer = setInterval(() => {
  if (!loading.value && ['pending', 'running'].includes(details.value?.portrait_status || ''))
    void load()
}, 5000)
onBeforeUnmount(() => clearInterval(timer))
const categories: Record<string, string> = {
  appearance: 'Appearance',
  background: 'Background',
  relationship: 'Relationships',
  belongings: 'Known belongings',
  equipment: 'Clothing and equipment',
  event: 'Events'
}
</script>

<template>
  <section
    class="flex min-h-0 min-w-0 flex-1 flex-col break-words text-sm"
    aria-label="Character details"
  >
    <div
      role="tablist"
      aria-label="Character details"
      class="grid shrink-0 grid-cols-2 gap-1 border-b border-white/10 bg-slate-950/40 p-3"
    >
      <button
        v-for="tab in ['state', 'history'] as const"
        :id="`${tabId}-section-${tab}`"
        :key="tab"
        type="button"
        role="tab"
        :data-section="tab"
        :aria-selected="activeTab === tab"
        :aria-controls="`${tabId}-section-${tab}-panel`"
        :tabindex="activeTab === tab ? 0 : -1"
        class="rounded-lg px-3 py-3 font-semibold focus-visible:outline-amber-300"
        :class="
          activeTab === tab ? 'bg-amber-400/15 text-amber-100' : 'text-slate-400 hover:bg-white/5'
        "
        @click="activeTab = tab"
        @keydown="navigateSections"
      >
        {{ tab === 'state' ? 'State & clothing' : 'History' }}
      </button>
    </div>
    <p v-if="error" role="alert" class="shrink-0 p-4 text-rose-300">
      {{ error }} <button type="button" class="underline" @click="load()">Retry</button>
    </p>
    <p v-if="loading && !details" role="status" class="p-4 text-slate-400">
      Loading character information…
    </p>
    <div
      v-if="details"
      ref="historyPanel"
      class="npc-history-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 sm:p-5"
    >
      <section
        v-show="activeTab === 'state'"
        :id="`${tabId}-section-state-panel`"
        role="tabpanel"
        :aria-labelledby="`${tabId}-section-state`"
        tabindex="0"
        class="space-y-4 focus-visible:outline-amber-300"
      >
        <button
          type="button"
          :disabled="loading"
          class="text-xs text-amber-200 underline disabled:opacity-50"
          @click="load()"
        >
          {{ loading ? 'Refreshing…' : 'Refresh observations' }}
        </button>
        <p
          v-if="['pending', 'running'].includes(details.portrait_status || '')"
          role="status"
          class="text-amber-200"
        >
          The first portrait is being prepared. You can continue playing.
        </p>
        <p
          v-else-if="['failed', 'interrupted'].includes(details.portrait_status || '')"
          class="text-slate-400"
        >
          The automatic portrait could not finish. Character information is saved; open Portrait
          options to retry.
        </p>
        <NpcCurrentState :state="details.current_state" />
        <details class="rounded-xl border border-slate-700 p-3">
          <summary class="cursor-pointer font-semibold">
            Relationships and emotional estimates
          </summary>
          <NpcRelationship class="mt-3" :relationship="details.relationship" />
          <NpcNarrativeInsights
            v-if="settings.showState.value && details.state_visible"
            class="mt-3"
            :insights="details.insights"
          />
        </details>
        <NpcCardPreferences :settings="settings" />
      </section>
      <section
        v-show="activeTab === 'history'"
        :id="`${tabId}-section-history-panel`"
        role="tabpanel"
        :aria-labelledby="`${tabId}-section-history`"
        tabindex="0"
        class="space-y-4 focus-visible:outline-amber-300"
        aria-label="Character history"
      >
        <div
          role="tablist"
          aria-label="Character history"
          class="grid grid-cols-2 gap-1 rounded-lg bg-slate-950/60 p-1"
        >
          <button
            v-for="tab in ['general', 'shared'] as const"
            :id="`${tabId}-${tab}`"
            :key="tab"
            type="button"
            role="tab"
            :data-history="tab"
            :aria-selected="history === tab"
            :aria-controls="`${tabId}-panel`"
            :tabindex="history === tab ? 0 : -1"
            class="rounded-md px-3 py-2 text-sm font-semibold focus-visible:outline-amber-300"
            :class="
              history === tab ? 'bg-amber-400/15 text-amber-100' : 'text-slate-400 hover:bg-white/5'
            "
            @click="history = tab"
            @keydown="navigateTabs"
          >
            {{ tab === 'general' ? 'General history' : 'History with your character' }}
            <span v-if="details.history_counts" class="ml-1 text-xs opacity-70">{{
              details.history_counts[tab]
            }}</span>
          </button>
        </div>
        <section
          :id="`${tabId}-panel`"
          role="tabpanel"
          :aria-labelledby="`${tabId}-${history}`"
          :aria-busy="loading"
          tabindex="0"
          class="mt-4 min-h-28 rounded-lg pb-2 focus-visible:outline-amber-300"
        >
          <section
            v-if="history === 'shared'"
            class="rounded-xl border border-amber-400/20 bg-amber-400/5 p-4"
            aria-label="Shared history summary"
          >
            <h3 class="font-semibold text-amber-100">Your shared history</h3>
            <p class="mt-1 text-xs text-slate-400">
              A few remembered moments you shared with this character.
            </p>
            <ul v-if="details.summary?.length" class="mt-3 space-y-3">
              <li
                v-for="entry in details.summary.slice(0, 4)"
                :key="entry.id"
                class="whitespace-pre-wrap"
              >
                <span v-if="entry.source === 'claimed'" class="mr-1 text-xs text-amber-200"
                  >Claim:</span
                >{{ entry.text }}
              </li>
            </ul>
            <p v-else class="mt-3 text-slate-400">
              No shared history recorded yet. Details appear as you get to know this character.
            </p>
          </section>

          <p class="mt-3 text-xs text-slate-400">
            {{
              history === 'general'
                ? 'Background, appearance and other facts your character has learned.'
                : 'Events you shared and how this character has responded to you.'
            }}
            Claims record what someone said, without assuming it is true. Belongings are past
            observations, not a live inventory.
          </p>
          <p v-if="history === 'general' && details.introduction" class="mt-3 text-slate-300">
            <span class="text-slate-400">Introduction:</span> “{{ details.introduction }}”
          </p>
          <p v-if="history === 'general' && details.aliases?.length" class="mt-2 text-slate-400">
            Also known as: {{ details.aliases.join(', ') }}
          </p>
          <p v-if="loading" role="status" class="mt-3 text-slate-400">Loading history…</p>
          <component
            :is="history === 'shared' ? 'details' : 'div'"
            :class="history === 'shared' ? 'mt-4 rounded-lg border border-slate-700 p-3' : ''"
          >
            <summary v-if="history === 'shared'" class="cursor-pointer font-semibold">
              All shared events · {{ details.history_counts?.shared ?? details.entry_count }}
            </summary>
            <p v-if="!loading && !error && !details.entries?.length" class="mt-3 text-slate-400">
              {{
                history === 'general'
                  ? 'No general history learned yet.'
                  : 'No shared events recorded yet.'
              }}
            </p>
            <ol class="mt-3 space-y-3">
              <li
                v-for="entry in details.entries"
                :key="entry.id"
                class="border-l-2 border-amber-500/30 pl-3"
              >
                <div class="text-xs text-amber-200">
                  {{ categories[entry.category] || entry.category }} ·
                  {{ entry.source === 'claimed' ? 'Claim' : 'Observed' }}
                </div>
                <p v-if="entry.game_minute != null" class="mt-1 text-xs text-slate-500">
                  Game minute {{ entry.game_minute }}
                </p>
                <p class="mt-1 whitespace-pre-wrap">{{ entry.text }}</p>
                <details class="mt-1 text-xs text-slate-400">
                  <summary class="cursor-pointer">Source passage</summary>
                  <blockquote class="mt-1 whitespace-pre-wrap">{{ entry.evidence }}</blockquote>
                </details>
              </li>
            </ol>
            <button
              v-if="details.has_more"
              type="button"
              :disabled="loading"
              class="mt-3 underline text-amber-200 disabled:opacity-50"
              @click="load(true)"
            >
              Load earlier entries
            </button>
          </component>
        </section>
      </section>
    </div>
  </section>
</template>

<style scoped>
.npc-history-scroll {
  scrollbar-width: thin;
  scrollbar-color: #64748b transparent;
  scrollbar-gutter: stable;
}
.npc-history-scroll::-webkit-scrollbar {
  width: 8px;
}
.npc-history-scroll::-webkit-scrollbar-thumb {
  background: #64748b;
  border-radius: 999px;
}
</style>
