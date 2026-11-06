import { ref, computed } from 'vue'

export type NotificationType = 'error' | 'success' | 'info'

export interface Notification {
  id: number
  message: string
  type: NotificationType
}

/**
 * Notification service for managing toast notifications
 */
class NotificationService {
  private notifications = ref<Notification[]>([])
  private nextId = 0
  private readonly DURATION_MS = 5000
  private timers = new Map<number, ReturnType<typeof setTimeout>>()

  get all() {
    return computed(() => this.notifications.value)
  }

  add(message: string, type: NotificationType = 'info', durationMs = this.DURATION_MS): number {
    const id = this.nextId++
    this.notifications.value.push({ id, message, type })

    const timer = setTimeout(() => {
      this.remove(id)
    }, durationMs)
    this.timers.set(id, timer)

    return id
  }

  remove(id: number): void {
    clearTimeout(this.timers.get(id))
    this.timers.delete(id)
    this.notifications.value = this.notifications.value.filter(n => n.id !== id)
  }

  clear(): void {
    this.timers.forEach(timer => clearTimeout(timer))
    this.timers.clear()
    this.notifications.value = []
  }

  success(message: string): number {
    return this.add(message, 'success')
  }

  error(message: string): number {
    return this.add(message, 'error')
  }

  info(message: string): number {
    return this.add(message, 'info')
  }
}

export const notificationService = new NotificationService()
