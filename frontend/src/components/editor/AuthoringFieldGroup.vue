<script setup lang="ts">
import { BookOpen, ChevronRight, Eye, HeartPulse, Package, UserRound } from 'lucide-vue-next'

withDefaults(defineProps<{
  title: string
  description?: string
  icon?: 'identity' | 'story' | 'state' | 'belongings' | 'visibility'
  collapsible?: boolean
  initiallyOpen?: boolean
}>(), { icon: 'story', collapsible: true, initiallyOpen: false })

const icons = { identity: UserRound, story: BookOpen, state: HeartPulse, belongings: Package, visibility: Eye }
</script>

<template>
  <details v-if="collapsible" :open="initiallyOpen" class="entity-field-group">
    <summary class="entity-field-heading">
      <component :is="icons[icon]" class="entity-field-icon" aria-hidden="true" />
      <span class="min-w-0 flex-1"><span class="entity-field-title">{{ title }}</span><span v-if="description" class="entity-field-description">{{ description }}</span></span>
      <ChevronRight class="entity-field-chevron" aria-hidden="true" />
    </summary>
    <div class="entity-field-body"><slot /></div>
  </details>
  <section v-else class="entity-field-group">
    <header class="entity-field-heading">
      <component :is="icons[icon]" class="entity-field-icon" aria-hidden="true" />
      <div><h4 class="entity-field-title">{{ title }}</h4><p v-if="description" class="entity-field-description">{{ description }}</p></div>
    </header>
    <div class="entity-field-body"><slot /></div>
  </section>
</template>

<style scoped>
.entity-field-group { border: 1px solid #293548; border-radius: 12px; background: #0d1522; }
.entity-field-heading { display: flex; align-items: center; gap: 12px; padding: 16px 18px; list-style: none; }
summary.entity-field-heading { cursor: pointer; }
summary::-webkit-details-marker { display: none; }
summary:focus-visible { outline: 2px solid #d6b46f; outline-offset: 3px; border-radius: 10px; }
.entity-field-title { display: block; color: #e5eaf2; font-size: 17px; font-weight: 600; }
.entity-field-description { display: block; margin-top: 3px; color: #8c9bb0; font-size: 13px; font-weight: 400; }
.entity-field-icon { width: 19px; height: 19px; flex-shrink: 0; color: #d6b46f; stroke-width: 1.6; }
.entity-field-chevron { width: 16px; height: 16px; flex-shrink: 0; color: #94a3b8; transition: transform .2s; }
details[open] > summary .entity-field-chevron { transform: rotate(90deg); }
.entity-field-body { padding: 0 18px 18px; display: grid; gap: 20px; min-width: 0; }
@media (prefers-reduced-motion: reduce) { .entity-field-chevron { transition: none; } }
</style>
