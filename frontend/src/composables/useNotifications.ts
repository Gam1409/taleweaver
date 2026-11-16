import { notificationService, type NotificationType } from '@/services/notificationService'

export type { Notification, NotificationType } from '@/services/notificationService'

/** Compatibility facade: gameplay and editor now use one notification store. */
export function useNotifications() {
  return {
    notifications: notificationService.all,
    addNotification: (message: string, type: NotificationType = 'info') =>
      notificationService.add(message, type, 8000),
    removeNotification: (id: number) => notificationService.remove(id),
  }
}

