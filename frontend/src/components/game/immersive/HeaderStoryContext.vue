<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { BookOpen, ChevronDown, Compass, Scroll } from 'lucide-vue-next'
import SessionDiagnosticsId from './SessionDiagnosticsId.vue'
import NpcBehaviorIndicator from './NpcBehaviorIndicator.vue'

const props = defineProps<{
  sceneName?: string | null
  activeSequence?: any | null
  adventureTitle?: string | null
  creator?: string | null
  copyright?: string | null
  trackedQuest?: any
  mode?: string
  debugMode?: boolean
  systemDebugEnabled?: boolean
  sessionId?: string
}>()
const emit = defineEmits<{ openQuests: [] }>()
const details = ref(false)
const context = ref<HTMLElement>()
const chapter = ref<HTMLElement>()
const chapterDetails = ref<HTMLElement>()
const placement = ref({ left: '0px', top: 'calc(100% + 11px)', width: '320px', maxHeight: '320px' })
const id = useId()
const title = computed(() =>
  String(
    props.activeSequence?.title || props.activeSequence?.name || props.activeSequence?.id || ''
  ).trim()
)
const description = computed(() =>
  String(
    props.activeSequence?.description ||
      props.activeSequence?.summary ||
      props.activeSequence?.teaser ||
      ''
  ).trim()
)
const quest = computed(() => props.trackedQuest?.title || props.trackedQuest?.description || '')

function placeDetails() {
  const anchor = chapter.value?.getBoundingClientRect()
  if (!details.value || !anchor) return
  const viewport = window.visualViewport
  const edge = viewport?.offsetLeft || 0
  const width = viewport?.width || window.innerWidth
  const topEdge = viewport?.offsetTop || 0
  const height = viewport?.height || window.innerHeight
  const panelWidth = Math.max(0, Math.min(320, width - 24))
  const left = Math.max(edge + 12, Math.min(anchor.left, edge + width - panelWidth - 12))
  const available = Math.min(320, Math.max(0, height - 24), Math.max(96, topEdge + height - anchor.bottom - 24))
  const panelHeight = Math.min((chapterDetails.value?.scrollHeight || available) + 2, available)
  const top = Math.max(topEdge + 12, Math.min(anchor.bottom + 11, topEdge + height - panelHeight - 12))
  placement.value = {
    left: `${left - anchor.left}px`, top: `${top - anchor.top}px`,
    width: `${panelWidth}px`, maxHeight: `${available}px`
  }
}
watch(details, async value => {
  if (!value) return
  await nextTick()
  placeDetails()
})
function closeOutside(event: PointerEvent) {
  if (!context.value?.contains(event.target as Node)) details.value = false
}
onMounted(() => {
  document.addEventListener('pointerdown', closeOutside)
  window.addEventListener('resize', placeDetails)
  window.visualViewport?.addEventListener('resize', placeDetails)
  window.visualViewport?.addEventListener('scroll', placeDetails)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', closeOutside)
  window.removeEventListener('resize', placeDetails)
  window.visualViewport?.removeEventListener('resize', placeDetails)
  window.visualViewport?.removeEventListener('scroll', placeDetails)
})
</script>

<template>
  <div ref="context" class="header-context">
    <div class="header-location">
      <Compass aria-hidden="true" />
      <h2 :title="sceneName || 'Unknown Location'">{{ sceneName || 'Unknown Location' }}</h2>
    </div>
    <div
      v-if="adventureTitle || title || copyright || creator || debugMode"
      class="header-metadata"
    >
      <span v-if="adventureTitle" class="header-adventure" :title="adventureTitle">{{
        adventureTitle
      }}</span>
      <div v-if="title" ref="chapter" class="header-chapter">
        <button
          type="button"
          :aria-expanded="details"
          :aria-controls="id"
          class="header-chapter-trigger"
          :title="title"
          @click="details = !details"
          @keydown.esc.stop.prevent="details = false"
        >
          <BookOpen aria-hidden="true" /><span
            >{{ activeSequence?.order ? `Chapter ${activeSequence.order} · ` : ''
            }}{{ title }}</span
          ><ChevronDown :class="{ expanded: details }" aria-hidden="true" />
        </button>
        <Transition name="chapter-details">
          <section v-if="details" :id="id" ref="chapterDetails" :style="placement" class="header-chapter-details" :aria-label="title">
            <span class="chapter-caption">{{
              activeSequence?.order ? `Chapter ${activeSequence.order}` : 'Current chapter'
            }}</span>
            <h3>{{ title }}</h3>
            <p>{{ description || 'No short description available for this sequence.' }}</p>
          </section>
        </Transition>
      </div>
      <span
        v-if="copyright || creator"
        class="header-credit"
        :title="copyright || `© ${creator}`"
        >{{ copyright || `© ${creator}` }}</span
      >
      <span v-if="debugMode" class="header-debug-status" title="Debug mode is active">Debug</span>
    </div>
    <div class="header-diagnostics">
      <SessionDiagnosticsId
        :enabled="!!systemDebugEnabled"
        :session-id="sessionId"
      /><NpcBehaviorIndicator :session-id="sessionId" />
    </div>
    <button
      v-if="quest && mode !== 'vn'"
      type="button"
      class="header-quest"
      :title="quest"
      @click="emit('openQuests')"
    >
      <Scroll aria-hidden="true" /><span class="quest-caption">Quest</span
      ><span class="quest-title">{{ quest }}</span>
    </button>
  </div>
</template>

<style scoped>
.header-context {
  min-width: 0;
  position: relative;
}
.header-location {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}
.header-location > svg {
  width: 17px;
  height: 17px;
  flex-shrink: 0;
  stroke-width: 1.5;
  color: #c8ac72;
}
.header-location h2 {
  font-family: var(--session-font, 'Alegreya Sans'), sans-serif;
  color: #f1f5f9;
  font-size: 18px;
  letter-spacing: 0.045em;
  text-transform: uppercase;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.35;
  margin: 0;
}
.header-metadata {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 3px 12px;
  min-width: 0;
  margin-top: 3px;
  font:
    11px/1.6 -apple-system,
    BlinkMacSystemFont,
    'Segoe UI',
    sans-serif;
  color: #94a3b8;
}
.header-adventure {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 270px;
}
.header-chapter {
  position: relative;
  min-width: 0;
  max-width: 100%;
}
.header-chapter-trigger {
  display: flex;
  align-items: center;
  gap: 5px;
  max-width: 100%;
  color: #c8ac72;
  font-size: 10px;
  padding: 0;
  text-align: left;
}
.header-chapter-trigger > svg {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
}
.header-chapter-trigger > svg:last-child {
  width: 10px;
  transition: transform 0.2s;
}
.header-chapter-trigger .expanded {
  transform: rotate(180deg);
}
.header-chapter-trigger > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 290px;
}
.header-chapter-trigger:hover {
  color: #fde68a;
}
.header-chapter-trigger:focus-visible,
.header-quest:focus-visible {
  outline: 2px solid #fbbf24;
  outline-offset: 3px;
  border-radius: 4px;
}
.header-credit {
  font-size: 9px;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #64748b;
}
.header-debug-status {
  color: #67a7b5;
  font-size: 9px;
  letter-spacing: 0.06em;
}
.header-diagnostics {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.header-diagnostics:empty {
  display: none;
}
.header-quest {
  display: flex;
  align-items: center;
  gap: 7px;
  max-width: min(100%, 560px);
  padding: 0;
  margin-top: 5px;
  text-align: left;
  font:
    11px/1.6 -apple-system,
    BlinkMacSystemFont,
    'Segoe UI',
    sans-serif;
  color: #b9c1cf;
}
.header-quest > svg {
  width: 13px;
  height: 13px;
  flex-shrink: 0;
  color: #b99b61;
}
.quest-caption {
  font-size: 9px;
  color: #748298;
  flex-shrink: 0;
}
.quest-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  word-spacing: 0.03em;
}
.header-quest:hover .quest-title {
  color: #fde68a;
}
.header-chapter-details {
  position: absolute;
  left: 0;
  top: calc(100% + 11px);
  z-index: 80;
  width: 320px;
  max-width: calc(100vw - 24px);
  overflow-y: auto;
  padding: 16px;
  border: 1px solid #695533;
  border-radius: 12px;
  background: rgb(9 16 30 / 0.98);
  backdrop-filter: blur(16px);
  box-shadow: 0 16px 48px #0008;
  color: #cbd5e1;
}
.chapter-caption {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: #d3b779;
}
.header-chapter-details h3 {
  font:
    600 14px/1.5 -apple-system,
    BlinkMacSystemFont,
    'Segoe UI',
    sans-serif;
  color: #f1f5f9;
  margin: 6px 0;
}
.header-chapter-details p {
  font:
    12px/1.75 -apple-system,
    BlinkMacSystemFont,
    'Segoe UI',
    sans-serif;
  max-height: 240px;
  overflow-y: auto;
  margin: 0;
}
.chapter-details-enter-active,
.chapter-details-leave-active {
  transition:
    opacity 0.18s,
    transform 0.18s;
}
.chapter-details-enter-from,
.chapter-details-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
@media (max-width: 700px) {
  .header-location h2 {
    font-size: 15px;
    letter-spacing: 0.025em;
  }
  .header-location {
    gap: 7px;
  }
  .header-location > svg {
    width: 15px;
    height: 15px;
  }
  .header-metadata {
    font-size: 10px;
    gap: 2px 8px;
  }
  .header-adventure {
    max-width: 100%;
  }
  .header-chapter-trigger {
    font-size: 9px;
  }
  .header-credit {
    font-size: 8px;
    max-width: 100%;
  }
  .header-quest {
    font-size: 10px;
    margin-top: 4px;
    gap: 5px;
  }
  .header-debug-status {
    font-size: 8px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .chapter-details-enter-active,
  .chapter-details-leave-active,
  .header-chapter-trigger > svg:last-child {
    transition-duration: 0.001ms;
  }
}
</style>
