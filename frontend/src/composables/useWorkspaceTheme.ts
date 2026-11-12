import { onScopeDispose } from 'vue'
import '@/assets/workspace.css'
import '@/assets/workspace-dialogs.css'

let consumers = 0

/** Share portal styling across route transitions without changing session language. */
export function useWorkspaceTheme() {
  if (typeof document === 'undefined') return
  consumers += 1
  document.documentElement.dataset.workspaceTheme = 'archive'
  onScopeDispose(() => {
    consumers -= 1
    if (consumers === 0) delete document.documentElement.dataset.workspaceTheme
  })
}
