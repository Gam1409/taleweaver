import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'
import ts from 'typescript'

const require = createRequire(import.meta.url)
export const stubComponent = { render: () => null }

// Exercise real component templates and event handlers without a browser or network.
export function loadSfc(path, dependencies = {}) {
  const source = readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const code = ts.transpileModule(compileScript(descriptor, {
    id: path, inlineTemplate: true,
  }).content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(
    name => dependencies[name] ?? require(name), module, module.exports,
  )
  return module.exports.default
}

export function mountSfc(path, initialProps, dependencies = {}) {
  const component = loadSfc(path, dependencies)
  const node = (type, text = '') => {
    const element = Object.assign(new EventTarget(), {
      type, text, props: {}, children: [], parent: null, value: '', getRootNode: () => body,
    })
    Object.defineProperty(element, 'options', { get: () => element.children.filter(child => child.type === 'option') })
    return element
  }
  const root = node('root'), body = node('body')
  const remove = child => {
    const children = child.parent?.children
    if (children) children.splice(children.indexOf(child), 1)
    child.parent = null
  }
  const renderer = createRenderer({
    createElement: type => {
      const element = node(type)
      element.showModal = () => { element.props.open = true }
      element.close = () => { element.props.open = false; element.props.onClose?.() }
      return element
    },
    createText: text => node('text', text), createComment: () => node('comment'),
    insertStaticContent(content, parent, anchor) {
      const child = node('static', content)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, child)
      child.parent = parent
      return [child, child]
    },
    insert(child, parent, anchor) {
      remove(child)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, child)
      child.parent = parent
    },
    remove, setText: (node, text) => { node.text = text },
    setElementText(node, text) { node.text = text; node.children = [] },
    patchProp: (node, key, _old, value) => {
      node.props[key] = value
      if (key === 'value') { node.value = value; node._value = value }
    },
    parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
    querySelector: selector => selector === 'body' ? body : null,
  })
  const props = reactive(initialProps)
  const app = renderer.createApp({ render: () => h(component, props) })
  app.mount(root)
  const all = () => {
    const walk = node => [node, ...node.children.flatMap(walk)]
    return [...walk(root), ...walk(body)]
  }
  const text = node => node.text + node.children.map(text).join('')
  return {
    app, props, all, text,
    button: label => all().find(node => node.type === 'button' && text(node).trim() === label),
  }
}

export async function settle() {
  await new Promise(resolve => setImmediate(resolve))
  await nextTick()
}
