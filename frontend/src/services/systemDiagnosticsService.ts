import { apiFetch } from '@/services/http'

export interface SystemDiagnosticsSettings {
  reliability?: { scope: string, recall: Record<string, number>, staging?: Record<string, number>, hooks?: { name: string, status: string, attempts: number, error_type: string | null, updated_at: string }[] }
  enabled: boolean
  detailed_logging?: boolean
  state_failure_traces?: boolean
  log_directory: string
  retention_files: number
  max_file_bytes?: number
  write_error?: string | null
}

async function request(enabled?: boolean, detailedLogging?: boolean, stateFailureTraces?: boolean): Promise<SystemDiagnosticsSettings> {
  const response = await apiFetch('/system-diagnostics', {
    method: enabled === undefined ? 'GET' : 'PUT',
    includeJson: enabled !== undefined,
    body: enabled === undefined ? undefined : JSON.stringify({
      enabled,
      ...(detailedLogging === undefined ? {} : { detailed_logging: detailedLogging }),
      ...(stateFailureTraces === undefined ? {} : { state_failure_traces: stateFailureTraces })
    })
  })
  if (!response.ok) {
    // Never display raw backend errors: they may include operational secrets.
    throw new Error(
      response.status === 403
        ? 'Only administrators can manage system diagnostics.'
        : 'Could not update system diagnostics. Check the server and try again.'
    )
  }
  const settings = await response.json() as SystemDiagnosticsSettings
  return { ...settings, state_failure_traces: settings.state_failure_traces === true }
}

export const systemDiagnosticsService = {
  getSettings: (): Promise<SystemDiagnosticsSettings> => request(),
  saveSettings: (enabled: boolean, detailedLogging?: boolean, stateFailureTraces?: boolean): Promise<SystemDiagnosticsSettings> => request(enabled, detailedLogging, stateFailureTraces)
}
