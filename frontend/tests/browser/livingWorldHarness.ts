import { createApp } from 'vue'
import LivingWorldSettings from '../../src/components/game/LivingWorldSettings.vue'
import { authState } from '../../src/store/auth'
authState.user = { id: 'fixture', username: 'Fixture', role: 'admin' }
createApp(LivingWorldSettings, { sessionId: 'fixture' }).mount('#app')
