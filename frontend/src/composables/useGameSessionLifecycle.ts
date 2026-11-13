import { onBeforeUnmount, onMounted, watch, type Ref } from 'vue'
import type { Router } from 'vue-router'
import { gameViewService, type GameSettings } from '@/services/gameViewService'

type UseGameSessionLifecycleOptions = {
  routeId: Ref<string>
  status: Ref<string>
  gameSettings: Ref<GameSettings>
  router: Router
  connect: (gameId: string) => Promise<void>
  disconnect: () => void
  closePanels: () => void
}

export function useGameSessionLifecycle(options: UseGameSessionLifecycleOptions): void {
  const {
    routeId,
    status,
    gameSettings,
    router,
    connect,
    disconnect,
    closePanels,
  } = options
  let generation = 0
  let disposed = false

  const connectWithRouteFallback = async (id: string) => {
    const request = ++generation
    const ownsRoute = () => !disposed && request === generation && routeId.value === id
    await connect(id)
    if (!ownsRoute() || status.value !== 'error') return

    const resolvedGameId = await gameViewService.ensureGameIdForRouteId(id)
    if (!ownsRoute() || !resolvedGameId || resolvedGameId === id) return

    await router.replace({ name: 'game', params: { id: resolvedGameId } })
  }

  const handleGlobalKeydown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      closePanels()
    }
  }

  onMounted(() => {
    void (async () => {
      const settings = await gameViewService.fetchGameSettings()
      if (settings && !disposed) {
        gameSettings.value = settings
      }
    })()

    if (routeId.value) {
      void connectWithRouteFallback(routeId.value)
    }

    window.addEventListener('keydown', handleGlobalKeydown)
  })

  watch(() => routeId.value, (newId) => {
    generation++
    disconnect()
    if (newId) {
      void connectWithRouteFallback(newId)
    }
  }, { flush: 'sync' })

  onBeforeUnmount(() => {
    disposed = true
    generation++
    disconnect()
    window.removeEventListener('keydown', handleGlobalKeydown)
  })
}
