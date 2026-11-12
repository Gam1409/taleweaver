<script setup lang="ts">
import { computed, useId } from 'vue'
import { BrainCircuit, Volume2 } from 'lucide-vue-next'
const props = defineProps<{
  turns: number
  enableCompression: boolean
  autoSpeakNarration: boolean
  autoSpeakDialogues: boolean
}>()
const emit = defineEmits<{
  'update:turns': [value: number]
  'update:enableCompression': [value: boolean]
  'update:autoSpeakNarration': [value: boolean]
  'update:autoSpeakDialogues': [value: boolean]
}>()
const id = useId()
const profile = computed(() =>
  props.turns <= 10
    ? {
        name: 'Balanced default',
        text: 'Balances continuity with efficient token usage before older turns are compacted.'
      }
    : props.turns <= 30
      ? {
          name: 'Extended memory',
          text: 'Keeps more turns before compaction and uses more tokens per response.'
        }
      : {
          name: 'Deep memory',
          text: 'Keeps a longer recent history for intricate plots, with higher token usage per response.'
        }
)
function input(event: Event) {
  const value = Number((event.target as HTMLInputElement).value)
  if (!Number.isNaN(value)) emit('update:turns', Math.min(100, Math.max(1, value)))
}
</script>

<template>
  <section class="memory-window" aria-label="Narrator memory">
    <div class="memory-title">
      <div>
        <label :for="`${id}-turns`">Narrator Turn Memory</label>
        <p>Past turns passed to the narrator in this session.</p>
      </div>
      <div class="memory-value">
        <input
          :id="`${id}-turns`"
          type="number"
          min="1"
          max="100"
          :value="turns"
          @input="input"
        /><span>turns</span>
      </div>
    </div>
    <input type="range" min="1" max="100" :value="turns" aria-label="Memory turns" @input="input" />
    <div class="memory-scale"><span>1</span><span>10 · default</span><span>100</span></div>
    <div class="memory-profile">
      <BrainCircuit aria-hidden="true" />
      <p>
        <strong>{{ profile.name }}</strong
        ><span>{{ profile.text }}</span>
      </p>
    </div>
  </section>
  <div class="memory-toggles">
    <label class="memory-setting"
      ><span
        ><strong>Automatic History Compression</strong
        ><small
          >Compress older turns into an English chronicle when the memory limit is reached.</small
        ></span
      ><input
        type="checkbox"
        :checked="enableCompression"
        @change="emit('update:enableCompression', ($event.target as HTMLInputElement).checked)"
    /></label>
    <div class="audio-caption"><Volume2 aria-hidden="true" />AUTO-SPEAK</div>
    <label class="memory-setting"
      ><span
        ><strong>Auto-Speak Game Master</strong
        ><small>Read narration aloud when Auto-Speak is enabled.</small></span
      ><input
        type="checkbox"
        :checked="autoSpeakNarration"
        @change="emit('update:autoSpeakNarration', ($event.target as HTMLInputElement).checked)"
    /></label>
    <label class="memory-setting"
      ><span
        ><strong>Auto-Speak Characters</strong
        ><small>Read NPC and player dialogue aloud when Auto-Speak is enabled.</small></span
      ><input
        type="checkbox"
        :checked="autoSpeakDialogues"
        @change="emit('update:autoSpeakDialogues', ($event.target as HTMLInputElement).checked)"
    /></label>
  </div>
</template>

<style scoped>
.memory-window {
  padding: 21px;
  border: 1px solid #2b384c;
  border-radius: 11px;
  background: #101a2b;
  margin-bottom: 23px;
}
.memory-title {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: center;
}
.memory-title label {
  font-size: 13px;
  font-weight: 550;
  color: #e1e9f4;
}
.memory-title p {
  font-size: 11px;
  color: #8192a9;
  margin: 4px 0 0;
}
.memory-value {
  display: flex;
  align-items: center;
  gap: 6px;
  border: 1px solid #43506a;
  padding: 6px 8px;
  border-radius: 7px;
  flex-shrink: 0;
  background: #0c1422;
}
.memory-value input {
  width: 42px;
  text-align: center;
  background: none;
  color: #e5d2ab;
  font: 600 15px/1.5 var(--session-font, 'Alegreya Sans'), sans-serif;
  outline: none;
}
.memory-value > span {
  color: #8c9aaf;
  font-size: 9px;
}
.memory-window > input[type='range'] {
  width: 100%;
  margin: 25px 0 7px;
  display: block;
  accent-color: #d3af6b;
  cursor: pointer;
  height: 4px;
}
.memory-scale {
  display: flex;
  justify-content: space-between;
  color: #64748b;
  font-size: 9px;
}
.memory-scale > span:nth-child(2) {
  color: #bd9e67;
}
.memory-profile {
  display: flex;
  gap: 10px;
  border-top: 1px solid #2a3548;
  margin-top: 20px;
  padding-top: 16px;
}
.memory-profile > svg {
  width: 15px;
  height: 15px;
  flex-shrink: 0;
  color: #c6a466;
  margin-top: 2px;
}
.memory-profile > p {
  margin: 0;
}
.memory-profile strong {
  display: block;
  color: #d6bd8c;
  font-size: 11px;
  font-weight: 500;
}
.memory-profile p > span {
  display: block;
  font-size: 11px;
  line-height: 1.8;
  color: #8899af;
  margin-top: 4px;
}
.memory-setting {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 26px;
  padding: 18px 1px;
  border-bottom: 1px solid #253146;
  cursor: pointer;
}
.memory-setting strong {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: #dce5f1;
}
.memory-setting small {
  display: block;
  font-size: 11px;
  line-height: 1.75;
  color: #7e91aa;
  margin-top: 4px;
}
.memory-setting input {
  position: relative;
  appearance: none;
  flex-shrink: 0;
  width: 35px;
  height: 20px;
  border-radius: 20px;
  border: 1px solid #44516a;
  background: #243045;
  cursor: pointer;
  transition:
    background 0.2s,
    border-color 0.2s;
}
.memory-setting input::after {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #8192aa;
  transition:
    transform 0.2s,
    background 0.2s;
}
.memory-setting input:checked {
  background: #b59558;
  border-color: #b59558;
}
.memory-setting input:checked::after {
  transform: translateX(15px);
  background: #f8f0df;
}
.memory-setting input:focus-visible {
  outline: 2px solid #d6b572;
  outline-offset: 4px;
}
.audio-caption {
  display: flex;
  gap: 7px;
  align-items: center;
  font-size: 8px;
  letter-spacing: 0.15em;
  color: #8b9eb5;
  margin-top: 26px;
}
.audio-caption svg {
  width: 13px;
  height: 13px;
  stroke-width: 1.5;
}
@media (max-width: 767px) {
  .memory-window {
    padding: 16px;
  }
  .memory-title {
    gap: 10px;
  }
  .memory-title label {
    font-size: 12px;
  }
  .memory-title p {
    font-size: 10px;
    max-width: 160px;
  }
  .memory-setting {
    gap: 16px;
  }
  .memory-setting strong {
    font-size: 11px;
  }
  .memory-setting small {
    font-size: 10px;
  }
  .memory-value input {
    width: 33px;
    font-size: 14px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .memory-setting input,
  .memory-setting input::after {
    transition-duration: 0.001ms;
  }
}
</style>
