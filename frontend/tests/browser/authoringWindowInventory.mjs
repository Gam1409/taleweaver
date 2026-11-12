import { readFileSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse } from '@vue/compiler-dom'

/** Discover static modal roots in the actual authoring component dependency graph. */
export function authoringWindowInventory() {
  const root = fileURLToPath(new URL('../../src/', import.meta.url))
  const queue = [resolve(root, 'views/CreateAdventureView.vue'), resolve(root, 'views/AdventureEditorView.vue')]
  const visited = new Set(), windows = [], counts = new Map()
  const classes = node => node.props?.find(prop => prop.type === 6 && prop.name === 'class')?.value?.content || ''
  function visit(node, file) {
    const isOverlay = /\bfixed\b/.test(classes(node)) && /\binset-0\b/.test(classes(node))
    if (node.type === 1 && (node.tag === 'dialog' || isOverlay)) {
      const index = counts.get(file) || 0
      windows.push({ file, window: index })
      counts.set(file, index + 1)
    }
    for (const child of node.children || []) visit(child, file)
  }
  while (queue.length) {
    const file = queue.shift()
    if (visited.has(file) || !existsSync(file)) continue
    visited.add(file)
    const source = readFileSync(file, 'utf8')
    for (const [, path] of source.matchAll(/from\s+['"]([^'"]+\.vue)['"]/g)) queue.push(path.startsWith('@/') ? resolve(root, path.slice(2)) : resolve(dirname(file), path))
    const start = source.indexOf('<template>'), end = source.lastIndexOf('</template>')
    if (start >= 0) visit(parse(source.slice(start + 10, end)), file.slice(root.length))
  }
  return windows
}
