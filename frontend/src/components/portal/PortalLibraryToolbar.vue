<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { FolderInput, Settings2, RefreshCw, RotateCcw, Trash2 } from 'lucide-vue-next'
import ActionGroupMenu from '@/components/game/immersive/ActionGroupMenu.vue'

const props = defineProps<{
  activeSection: 'templates' | 'sessions'
  templateCount?: number
  isDeletingTemplates?: boolean
  sessionCount?: number
  isDeletingSessions?: boolean
  updateCount?: number
  isUpdatingAll?: boolean
}>()
const emit = defineEmits<{
  (e: 'changeSection', section: 'templates' | 'sessions'): void
  (e: 'import', kind?: 'templates' | 'sessions'): void
  (e: 'restore-defaults'): void
  (e: 'delete-all-adventures'): void
  (e: 'delete-all-sessions'): void
  (e: 'update-all'): void
}>()
const menuOpen = ref(false)
const isLibrary = computed(() => props.activeSection === 'templates')
const deleting = computed(() => isLibrary.value ? props.isDeletingTemplates : props.isDeletingSessions)
const count = computed(() => (isLibrary.value ? props.templateCount : props.sessionCount) || 0)
watch(() => props.activeSection, () => { menuOpen.value = false })
</script>

<template>
  <header class="portal-heading">
    <div class="min-w-0">
      <p class="portal-eyebrow">Your archive</p>
      <h2>{{ isLibrary ? 'Library' : 'Game sessions' }}</h2>
      <p class="portal-subtitle">{{ isLibrary ? 'Every world begins with a story.' : 'Pick up a story where you left it.' }}</p>
    </div>
    <div class="portal-heading-actions">
      <button type="button" class="workspace-button" @click="emit('import', activeSection)">
        <FolderInput aria-hidden="true" />
        <span>{{ isLibrary ? 'Import adventure' : 'Import session' }}</span>
      </button>
      <ActionGroupMenu v-model="menuOpen" label="Manage" :icon="Settings2" :glow="isLibrary && !!updateCount">
        <button v-if="isLibrary && (updateCount || 0) > 0" type="button" role="menuitem" class="action-menu-item" :disabled="isUpdatingAll" @click="emit('update-all')">
          <RefreshCw :class="{ 'animate-spin': isUpdatingAll }" aria-hidden="true" />
          <span class="action-menu-copy"><span class="action-menu-title">{{ isUpdatingAll ? 'Updating…' : `Update all (${updateCount})` }}</span><span class="action-menu-description">Apply available adventure updates</span></span>
        </button>
        <button v-if="isLibrary" type="button" role="menuitem" class="action-menu-item" @click="emit('restore-defaults')">
          <RotateCcw aria-hidden="true" />
          <span class="action-menu-copy"><span class="action-menu-title">Restore defaults</span><span class="action-menu-description">Restore the bundled adventures</span></span>
        </button>
        <button type="button" role="menuitem" class="action-menu-item workspace-danger" :disabled="count === 0 || !!deleting" @click="isLibrary ? emit('delete-all-adventures') : emit('delete-all-sessions')">
          <Trash2 aria-hidden="true" />
          <span class="action-menu-copy"><span class="action-menu-title">{{ deleting ? 'Deleting…' : isLibrary ? 'Delete all adventures' : 'Delete all sessions' }}</span><span class="action-menu-description">Review and confirm before deleting</span></span>
        </button>
      </ActionGroupMenu>
    </div>
  </header>
</template>
