<script setup lang="ts">
export interface WardrobeMention {
  kind: string
  label: string
  status: 'proposed' | 'explained' | 'unreviewed'
  sources: { source_message_id: string; excerpt: string }[]
  omissions?: { reason: string; source_message_id: string; evidence: string }[]
}
defineProps<{ checks: WardrobeMention[] }>()
</script>
<template>
  <section class="space-y-2 rounded border border-amber-900 p-3">
    <h4 class="font-bold">Explicit underwear mentions</h4>
    <p class="text-xs text-slate-400">
      A limited English/Russian vocabulary check of narrator messages. Mentions alone do not
      establish current ownership; proposed entries must still pass the checks above.
    </p>
    <article v-for="check in checks" :key="check.kind" class="space-y-1">
      <strong>{{ check.label }}</strong>
      <p v-if="check.status === 'proposed'" class="text-cyan-200">
        Included in the proposal — see its validation result.
      </p>
      <p v-else-if="check.status === 'unreviewed'" class="text-amber-200">
        Mentioned but not accounted for. This garment has not been recovered. The model did not
        provide a valid explanation for omitting it.
      </p>
      <div v-for="(omission, index) in check.omissions" :key="index" class="space-y-1">
        <p class="text-amber-200">Model's reason for omission: {{ omission.reason }}</p>
        <blockquote class="border-l-2 border-slate-500 pl-2">{{ omission.evidence }}</blockquote>
        <p class="break-all text-xs text-slate-400">Source: {{ omission.source_message_id }}</p>
      </div>
      <details>
        <summary class="cursor-pointer text-cyan-200">Mentioned in the reviewed history</summary>
        <div v-for="source in check.sources" :key="source.source_message_id" class="my-2">
          <blockquote class="whitespace-pre-wrap border-l-2 border-slate-500 pl-2">
            {{ source.excerpt }}
          </blockquote>
          <p class="break-all text-xs text-slate-400">Source: {{ source.source_message_id }}</p>
        </div>
      </details>
    </article>
  </section>
</template>
