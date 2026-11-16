import { ref } from 'vue'

/** Discovery results and active requests belong to a URL, never just a provider name. */
export function createEndpointModelCache(fetchModels: (url: string) => Promise<string[]>) {
  const models = ref<Record<string, string[]>>({})
  const loading = ref<Record<string, boolean>>({})
  const pending = new Map<string, Promise<string[]>>()
  function load(rawUrl: string): Promise<string[]> {
    const url = rawUrl.trim().replace(/\/+$/, '')
    if (!url) return Promise.resolve([])
    const existing = pending.get(url)
    if (existing) return existing
    loading.value = { ...loading.value, [url]: true }
    const request = Promise.resolve().then(() => fetchModels(url)).then(result => {
      models.value = { ...models.value, [url]: result }
      return result
    }).catch(error => {
      models.value = { ...models.value, [url]: [] }
      throw error
    }).finally(() => {
      pending.delete(url)
      loading.value = { ...loading.value, [url]: false }
    })
    pending.set(url, request)
    return request
  }
  return { models, loading, load }
}
