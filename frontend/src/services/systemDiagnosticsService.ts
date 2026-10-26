import { apiFetch } from '@/services/http'

export interface SystemDiagnosticsSettings {
  enabled: boolean
  log_directory: string
  retention_files: number
  write_error?: string | null
}

async function request(enabled?: boolean): Promise<SystemDiagnosticsSettings> {
  const response = await apiFetch('/system-diagnostics', {
    method: enabled === undefined ? 'GET' : 'PUT',
    includeJson: enabled !== undefined,
    body: enabled === undefined ? undefined : JSON.stringify({ enabled })
  })
  if (!response.ok) {
    // Never display raw backend errors: they may include operational secrets.
    throw new Error(
      response.status === 403
        ? 'Only administrators can manage system diagnostics.'
        : 'Could not update system diagnostics. Check the server and try again.'
    )
  }
  return response.json() as Promise<SystemDiagnosticsSettings>
}

export const systemDiagnosticsService = {
  getSettings: (): Promise<SystemDiagnosticsSettings> => request(),
  saveSettings: (enabled: boolean): Promise<SystemDiagnosticsSettings> => request(enabled)
}
