import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import NpcPortraitModal from '../../src/components/game/NpcPortraitModal.vue'
import type { PortraitTarget } from '../../src/composables/useSessionPortrait'
import Stage from '../../src/components/game/immersive/ImmersiveCharacterStage.vue'
import DebugPlayerLocation from '../../src/components/game/DebugPlayerLocation.vue'
import SessionPortraitSettings from '../../src/components/game/SessionPortraitSettings.vue'
import SessionDiagnosticsId from '../../src/components/game/immersive/SessionDiagnosticsId.vue'
import type { PortraitPreferences } from '../../src/utils/npcPresentation'

createApp({
  setup() {
    const preferences = ref<PortraitPreferences>({ emotion_palette: true, character_thoughts: true, brightness: 40 })
    Object.assign(window, { npcPresentationFixture: { setMaximum() { for (const cue of Object.values(cues)) cue.intensity = 100; preferences.value = { emotion_palette: true, character_thoughts: true, brightness: 100 } } } })
    const thoughtsOnly = () => { preferences.value = { ...preferences.value, emotion_palette: false, character_thoughts: true } }
    const off = () => { preferences.value = { ...preferences.value, character_thoughts: false, emotion_palette: false } }
    const settings = ref<InstanceType<typeof SessionPortraitSettings> | null>(null)
    const manualMove = ref('')
    const clicks = ref(0)
    const hovered = ref(0)
    const portrait = ref<PortraitTarget | null>(null)
    const cues = { RIN: { emotion: 'fear', intensity: 75, thought: '<script>stay calm</script>' }, MIKI: { emotion: 'love', intensity: 90, thought: 'I wish this moment could last.' }, SAKI: { emotion: 'calm', intensity: 60, thought: 'Everything can wait a little.' } }
    return () => h('main', { class: 'min-h-screen bg-slate-950 text-white p-8' }, [
      h('h1', { class: 'text-xl mb-6' }, 'Portrait presentation'),
      portrait.value ? h(NpcPortraitModal, { npc: portrait.value, sessionId: 'fixture', busy: false, error: '', updated: false, onClose: () => { portrait.value = null } }) : null,
      h(SessionDiagnosticsId, { enabled: false, sessionId: 'fixture' }),
      h('div', { class: 'flex gap-12' }, [
        h('div', { class: 'h-[600px]' }, h(Stage, {
          npcs: [{ id: 'RIN', name: 'Dr. Rin' }, { id: 'MIKI', name: 'Miki' }, { id: 'SAKI', name: 'Saki' }, { id: 'UNASSESSED', name: 'Unassessed NPC' }],
          activeSpeakers: new Set(['RIN']), mode: 'vn', portraitCues: cues, portraitPreferences: preferences.value,
          onNpcClick: () => { clicks.value++ },
          onNpcHover: () => { hovered.value++ },
          onPortrait: npc => { portrait.value = npc },
        })),
        h('section', { class: 'w-96' }, [
          h(DebugPlayerLocation, { sceneId: 'RESEARCH_LAB', currentSceneId: 'HOSPITAL_CORRIDOR', busy: false, onCommand: command => { manualMove.value = command } }),
          h('p', { id: 'manual-player-move' }, manualMove.value),
          h(SessionPortraitSettings, { ref: settings, sessionId: 'fixture' }),
          h('button', { onClick: () => settings.value?.save(), class: 'mt-4 rounded-xl bg-cyan-700 px-4 py-2' }, 'Save presentation'),
          h('button', { onClick: thoughtsOnly, class: 'mt-4 block' }, 'Thoughts only'),
          h('button', { onClick: off, class: 'mt-4 block' }, 'Disable effects'),
          h('p', { id: 'portrait-clicks' }, String(clicks.value)),
          h('p', { id: 'legacy-hovers' }, String(hovered.value)),
        ]),
      ]),
    ])
  },
}).mount('#app')
