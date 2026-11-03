import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(new URL('../src/services/comfyWorkflowGraph.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText
const service = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

const twoSamplerGraph = {
  '1': {
    class_type: 'CheckpointLoaderSimple',
    inputs: { ckpt_name: 'model.safetensors' },
    _meta: { title: 'Load checkpoint' }
  },
  '2': {
    class_type: 'CLIPTextEncode',
    inputs: { text: 'a cozy tavern', clip: ['1', 1] },
    _meta: { title: 'Positive prompt' }
  },
  '3': {
    class_type: 'CLIPTextEncode',
    inputs: { text: 'blurry, deformed', clip: ['1', 1] },
    _meta: { title: 'Negative prompt' }
  },
  '4': {
    class_type: 'EmptyLatentImage',
    inputs: { width: 1024, height: 1024, batch_size: 1 }
  },
  '5': {
    class_type: 'KSampler',
    inputs: {
      seed: 12, steps: 20, cfg: 7, sampler_name: 'euler', scheduler: 'normal', denoise: 1,
      model: ['1', 0], positive: ['2', 0], negative: ['3', 0], latent_image: ['4', 0]
    }
  },
  '6': {
    class_type: 'KSampler',
    inputs: {
      seed: 34, steps: 10, cfg: 4.5, sampler_name: 'euler', scheduler: 'karras', denoise: 0.55,
      model: ['1', 0], positive: ['2', 0], negative: ['3', 0], latent_image: ['5', 0]
    }
  },
  '7': { class_type: 'VAEDecode', inputs: { samples: ['6', 0], vae: ['1', 2] } },
  '8': { class_type: 'SaveImage', inputs: { filename_prefix: 'out', images: ['7', 0] } },
  '9': {
    class_type: 'LoadImage',
    inputs: { image: 'example.png', upload: 'POST' }
  }
}

const workflow = () => ({
  name: 'Imported',
  graph: JSON.parse(JSON.stringify(twoSamplerGraph)),
  bindings: {},
  output_node: ''
})

test('suggestBindings maps a two-sampler workflow to the base pass', () => {
  const { suggestBindings } = service
  const suggestion = suggestBindings(twoSamplerGraph)
  assert.deepEqual(suggestion.bindings.prompt, { node_id: '2', input_name: 'text' })
  assert.deepEqual(suggestion.bindings.negative_prompt, { node_id: '3', input_name: 'text' })
  assert.deepEqual(suggestion.bindings.seed, { node_id: '5', input_name: 'seed' })
  assert.deepEqual(suggestion.bindings.width, { node_id: '4', input_name: 'width' })
  assert.deepEqual(suggestion.bindings.height, { node_id: '4', input_name: 'height' })
  assert.deepEqual(suggestion.bindings.image, { node_id: '9', input_name: 'image' })
  assert.equal(suggestion.output_node, '8')
  assert.ok(suggestion.notes.length >= 6)
})

test('suggestBindings falls back to encoder titles without samplers', () => {
  const { suggestBindings } = service
  const graph = {
    a: { class_type: 'LoadCheckpoint', inputs: { ckpt: 'x.safetensors' } },
    b: { class_type: 'CLIPTextEncode', inputs: { text: 'good', clip: ['a', 1] }, _meta: { title: 'Positive prompt' } },
    c: { class_type: 'CLIPTextEncode', inputs: { text: 'bad', clip: ['a', 1] }, _meta: { title: 'Negative prompt' } },
    d: { class_type: 'SaveImage', inputs: { images: ['b', 0] } }
  }
  const suggestion = suggestBindings(graph)
  assert.deepEqual(suggestion.bindings.prompt, { node_id: 'b', input_name: 'text' })
  assert.deepEqual(suggestion.bindings.negative_prompt, { node_id: 'c', input_name: 'text' })
  assert.equal(suggestion.output_node, 'd')
})

test('eligibleInputs follows the backend typing rules', () => {
  const { eligibleInputs } = service
  const text = eligibleInputs(twoSamplerGraph, 'prompt')
  assert.ok(text.some(t => t.node_id === '2' && t.input_name === 'text'))
  assert.ok(text.some(t => t.node_id === '1' && t.input_name === 'ckpt_name'))
  assert.ok(!text.some(t => t.input_name === 'seed'))
  assert.ok(!text.some(t => t.input_name === 'positive'), 'connected sockets are never eligible')
  const seeds = eligibleInputs(twoSamplerGraph, 'seed')
  assert.ok(seeds.some(t => t.node_id === '5' && t.input_name === 'seed'))
  assert.ok(seeds.some(t => t.node_id === '4' && t.input_name === 'width'))
  assert.ok(!seeds.some(t => t.node_id === '6' && t.input_name === 'cfg'), 'fractional numbers are not integer inputs')
  assert.ok(!seeds.some(t => t.input_name === 'text'))
})

test('autoLayout places every node and keeps edges flowing right', () => {
  const { autoLayout, edges, nodeSize, outputCounts } = service
  const positions = autoLayout(twoSamplerGraph)
  const ids = Object.keys(twoSamplerGraph)
  assert.equal(Object.keys(positions).length, ids.length)
  for (const id of ids) {
    assert.ok(Number.isFinite(positions[id].x), `${id} x`)
    assert.ok(Number.isFinite(positions[id].y), `${id} y`)
  }
  const counts = outputCounts(twoSamplerGraph)
  assert.equal(counts['1'], 3, 'checkpoint exposes three sockets')
  const sizes = {}
  for (const id of ids) sizes[id] = nodeSize(twoSamplerGraph[id], counts[id])
  for (const edge of edges(twoSamplerGraph)) {
    const from = positions[edge.from]
    const to = positions[edge.to]
    assert.ok(from.x + sizes[edge.from].width <= to.x + 1e-6, `${edge.from} must sit left of ${edge.to}`)
  }
  const byColumn = {}
  for (const id of ids) {
    const key = positions[id].x
    byColumn[key] ??= []
    byColumn[key].push(id)
  }
  for (const column of Object.values(byColumn)) {
    const boxes = column
      .map(id => ({ top: positions[id].y, bottom: positions[id].y + sizes[id].height }))
      .sort((a, b) => a.top - b.bottom)
    for (let i = 1; i < boxes.length; i++) {
      assert.ok(boxes[i].top >= boxes[i - 1].bottom, 'nodes in one column must not overlap')
    }
  }
})

test('positions round-trip through _meta.pos', () => {
  const { autoLayout, withPositions, existingPositions } = service
  const graph = JSON.parse(JSON.stringify(twoSamplerGraph))
  assert.equal(existingPositions(graph), null, 'fresh imports have no stored positions')
  const positions = autoLayout(graph)
  const placed = withPositions(graph, positions)
  const restored = existingPositions(placed)
  assert.equal(Object.keys(restored).length, Object.keys(graph).length)
  for (const [id, position] of Object.entries(restored)) {
    assert.equal(position.x, Math.round(positions[id].x))
    assert.equal(position.y, Math.round(positions[id].y))
  }
  assert.equal(placed['5']._meta.pos.length, 2)
  assert.equal(placed['1'].class_type, 'CheckpointLoaderSimple', 'withPositions preserves the node')
})

test('setBinding enforces the backend contract, clearBinding removes', () => {
  const { setBinding, clearBinding } = service
  const next = setBinding(workflow(), 'prompt', { node_id: '2', input_name: 'text' })
  assert.deepEqual(next.bindings.prompt, { node_id: '2', input_name: 'text' })
  assert.throws(() => setBinding(next, 'seed', { node_id: '2', input_name: 'text' }), /whole-number/)
  assert.throws(() => setBinding(next, 'negative_prompt', { node_id: '2', input_name: 'text' }), /already serves the Prompt role/)
  assert.throws(() => setBinding(next, 'prompt', { node_id: '404', input_name: 'text' }), /missing/)
  const cleared = clearBinding(next, 'prompt')
  assert.equal(cleared.bindings.prompt, undefined)
  const original = workflow()
  const untouched = clearBinding(original, 'seed')
  assert.equal(untouched, original, 'clearing a missing role is a no-op')
})
