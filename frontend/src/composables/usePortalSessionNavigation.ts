import { ref, type Ref } from 'vue'
import type { Router } from 'vue-router'
import type { UsePortalDataResult } from './usePortalData'

type SessionData = Pick<
  UsePortalDataResult,
  | 'templates'
  | 'sessions'
  | 'isStartingSession'
  | 'startingSessionTemplateId'
  | 'startingSessionTitle'
  | 'startSessionForTemplate'
>

interface SessionNavigation {
  isResuming: Ref<boolean>
  playSession: (gameId: string) => Promise<void>
  startSession: (templateId: string) => Promise<void>
}

export function usePortalSessionNavigation(data: SessionData, router: Router): SessionNavigation {
  const isResuming = ref(false)

  async function playSession(gameId: string): Promise<void> {
    if (data.isStartingSession.value) return
    const session = data.sessions.value.find(entry => entry.game_id === gameId)
    if (!session) return

    data.isStartingSession.value = true
    isResuming.value = true
    data.startingSessionTemplateId.value = session.template_id || session.adventure_id
    data.startingSessionTitle.value = session.adventure_title || 'Adventure'
    try {
      await router.push({
        name: 'game',
        params: { id: gameId },
        query: { title: session.adventure_title || '', resuming: 'true' }
      })
    } finally {
      data.isStartingSession.value = false
      data.startingSessionTemplateId.value = null
      data.startingSessionTitle.value = ''
      isResuming.value = false
    }
  }

  async function startSession(templateId: string): Promise<void> {
    if (data.isStartingSession.value) return
    await data.startSessionForTemplate(templateId, async gameId => {
      const template = data.templates.value.find(entry => entry.template_id === templateId)
      await router.push({
        name: 'game',
        params: { id: gameId },
        query: { title: template?.title || '', is_new: 'true' }
      })
    })
  }

  return { isResuming, playSession, startSession }
}
