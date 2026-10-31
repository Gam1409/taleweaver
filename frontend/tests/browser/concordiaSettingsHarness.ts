import { createApp, defineComponent, h, ref } from 'vue'
import AdventureGameSettings from '../../src/components/create-adventure/AdventureGameSettings.vue'
import LivingWorldAdventureButton from '../../src/components/living-world/LivingWorldAdventureButton.vue'
import '../../src/assets/main.css'
const Harness = defineComponent({
  setup() {
    const form = ref<any>({ rule_enforcement_mode: 'story', clock_enabled: false, pacing_minutes: 5, time_auto: true, can_damage_npcs: false, npcs_can_damage_protagonist: false })
    const saved = ref(0)
    return () => h('main', { class: 'min-h-screen bg-slate-950 p-6 text-white' }, [
      h('div', { class: 'mx-auto max-w-3xl space-y-6' }, [
        h(AdventureGameSettings, { modelValue: form.value, 'onUpdate:modelValue': value => { form.value = value } }),
        h('h2', 'Editor preview'),
        form.value.rule_enforcement_mode === 'vn' ? h(LivingWorldAdventureButton, {
          existing: true, modelValue: form.value.living_world_settings,
          'onUpdate:modelValue': value => { form.value.living_world_settings = value },
          onSave: () => { saved.value++ },
        }) : null,
        h('output', { id: 'saved' }, String(saved.value)),
        h('pre', { id: 'preferences' }, JSON.stringify(form.value.living_world_settings || {})),
      ]),
    ])
  },
})
createApp(Harness).mount('#app')
