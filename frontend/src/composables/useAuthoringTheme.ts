import { onScopeDispose } from 'vue'
import { useWorkspaceTheme } from './useWorkspaceTheme'
import '@/assets/authoring.css'
import '@/assets/authoring-dialogs.css'

let consumers = 0

export function useAuthoringTheme() {
  useWorkspaceTheme()
  if (typeof document === 'undefined') return
  consumers += 1
  document.documentElement.dataset.authoringTheme = 'archive'
  onScopeDispose(() => {
    consumers -= 1
    if (consumers === 0) delete document.documentElement.dataset.authoringTheme
  })
}
