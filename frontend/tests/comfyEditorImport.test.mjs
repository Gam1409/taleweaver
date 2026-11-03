/* eslint-env node */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const compileTs = path =>
  ts.transpileModule(readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
  }).outputText

const toDataUrl = code => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`

const serviceCode = compileTs('services/comfyWorkflowService.ts')
const editorCode = compileTs('services/comfyEditorImport.ts').replaceAll(
  "'@/services/comfyWorkflowService'",
  `'${toDataUrl(serviceCode)}'`
)
const editor = await import(toDataUrl(editorCode))

const graphCode = compileTs('services/comfyWorkflowGraph.ts')
const graphService = await import(toDataUrl(graphCode))

/* A real editor export from ComfyUI 1.57: 15 nodes, 21 links, three of the
 * six LoraLoaders bypassed (mode 4), one CLIPTextEncode collapsed. */
const pos = (x, y) => [x, y]
const lora = (id, p, name, sm, sc, modelLink, clipLink, outModel, outClip, mode = 0) => ({
  id,
  type: 'LoraLoader',
  pos: p,
  mode,
  inputs: [
    { name: 'model', type: 'MODEL', link: modelLink },
    { name: 'clip', type: 'CLIP', link: clipLink }
  ],
  outputs: [
    { name: 'MODEL', type: 'MODEL', links: [outModel] },
    { name: 'CLIP', type: 'CLIP', links: [outClip] }
  ],
  widgets_values_named: { lora_name: name, strength_model: sm, strength_clip: sc }
})

const positiveText = 'masterpiece, best quality, 1girl, mai_satomihh, rooftop'
const negativeText = 'negative_hand, watermark, worst quality, bad anatomy'

const editorWorkflow = {
  nodes: [
    {
      id: 10,
      type: 'KSampler',
      pos: pos(1268.02, -170.65),
      mode: 0,
      inputs: [
        { name: 'model', type: 'MODEL', link: 118 },
        { name: 'positive', type: 'CONDITIONING', link: 91 },
        { name: 'negative', type: 'CONDITIONING', link: 71 },
        { name: 'latent_image', type: 'LATENT', link: 123 }
      ],
      outputs: [{ name: 'LATENT', type: 'LATENT', links: [16] }],
      widgets_values_named: {
        seed: 981998850141260,
        control_after_generate: 'randomize',
        steps: 15,
        cfg: 1.2,
        sampler_name: 'euler_ancestral',
        scheduler: 'karras',
        denoise: 1
      }
    },
    {
      id: 16,
      type: 'SaveImage',
      pos: pos(798.84, 794.82),
      mode: 0,
      inputs: [{ name: 'images', type: 'IMAGE', link: 18 }],
      outputs: [],
      widgets_values_named: { filename_prefix: 'ComfyUI' }
    },
    lora(
      17,
      pos(129.75, 132.11),
      'character_lora\\XL\\mai_tomokohh.safetensors',
      0.8,
      1,
      117,
      116,
      94,
      99
    ),
    lora(
      61,
      pos(115.58, 312.37),
      'character_lora\\XL\\IL RUSSIAN\\BSS_RSGRL_IL.safetensors',
      0.8,
      1,
      94,
      99,
      93,
      97,
      4
    ),
    lora(
      62,
      pos(108.58, 497.64),
      'character_lora\\XL\\IL eyes\\EyesV1_400.safetensors',
      0.6,
      1,
      93,
      97,
      92,
      96,
      4
    ),
    lora(
      23,
      pos(479.99, 703.81),
      'H\\H_画风\\Expressive_H-000001.safetensors',
      0.3,
      1,
      102,
      103,
      118,
      128
    ),
    lora(
      63,
      pos(-16.78, 698.03),
      'Artist\\艺术风格\\style1XL\\style1.safetensors',
      0.3,
      1,
      92,
      96,
      100,
      101
    ),
    lora(
      64,
      pos(229.09, 703.81),
      'Artist\\艺术风格\\IL Real\\realistic filter [IL].safetensors',
      1,
      1,
      100,
      101,
      102,
      103,
      4
    ),
    {
      id: 84,
      type: 'EmptyLatentImage',
      pos: pos(1009.64, -32.64),
      mode: 0,
      inputs: [],
      outputs: [{ name: 'LATENT', type: 'LATENT', links: [123] }],
      widgets_values_named: { width: 1280, height: 1920, batch_size: 1 }
    },
    {
      id: 11,
      type: 'CheckpointLoaderSimple',
      pos: pos(597.35, -29.03),
      mode: 0,
      inputs: [],
      outputs: [
        { name: 'MODEL', type: 'MODEL', links: [117] },
        { name: 'CLIP', type: 'CLIP', links: [116] },
        { name: 'VAE', type: 'VAE', links: [] }
      ],
      widgets_values_named: { ckpt_name: 'IL\\uncannyValley_Noob3dV3.safetensors' }
    },
    {
      id: 18,
      type: 'VAELoader',
      pos: pos(777.49, -151.3),
      mode: 0,
      inputs: [],
      outputs: [{ name: 'VAE', type: 'VAE', links: [121] }],
      widgets_values_named: { vae_name: 'pony_sdxl_vae.safetensors' }
    },
    {
      id: 15,
      type: 'VAEDecode',
      pos: pos(1057.83, -141.06),
      mode: 0,
      inputs: [
        { name: 'samples', type: 'LATENT', link: 16 },
        { name: 'vae', type: 'VAE', link: 121 }
      ],
      outputs: [{ name: 'IMAGE', type: 'IMAGE', links: [18] }],
      widgets_values: []
    },
    {
      id: 14,
      type: 'CLIPTextEncode',
      pos: pos(722.9, 514.58),
      mode: 0,
      flags: { collapsed: true },
      inputs: [{ name: 'clip', type: 'CLIP', link: 127 }],
      outputs: [{ name: 'CONDITIONING', type: 'CONDITIONING', links: [71] }],
      widgets_values_named: { text: negativeText }
    },
    {
      id: 13,
      type: 'CLIPTextEncode',
      pos: pos(715.79, 123.68),
      mode: 0,
      inputs: [{ name: 'clip', type: 'CLIP', link: 126 }],
      outputs: [{ name: 'CONDITIONING', type: 'CONDITIONING', links: [91] }],
      widgets_values_named: { text: positiveText }
    },
    {
      id: 88,
      type: 'CLIPSetLastLayer',
      pos: pos(508.45, -153.09),
      mode: 0,
      inputs: [{ name: 'clip', type: 'CLIP', link: 128 }],
      outputs: [{ name: 'CLIP', type: 'CLIP', links: [126, 127] }],
      widgets_values_named: { stop_at_clip_layer: -2 }
    }
  ],
  links: [
    [16, 10, 0, 15, 0, 'LATENT'],
    [18, 15, 0, 16, 0, 'IMAGE'],
    [71, 14, 0, 10, 2, 'CONDITIONING'],
    [91, 13, 0, 10, 1, 'CONDITIONING'],
    [92, 62, 0, 63, 0, 'MODEL'],
    [93, 61, 0, 62, 0, 'MODEL'],
    [94, 17, 0, 61, 0, 'MODEL'],
    [96, 62, 1, 63, 1, 'CLIP'],
    [97, 61, 1, 62, 1, 'CLIP'],
    [99, 17, 1, 61, 1, 'CLIP'],
    [100, 63, 0, 64, 0, 'MODEL'],
    [101, 63, 1, 64, 1, 'CLIP'],
    [102, 64, 0, 23, 0, 'MODEL'],
    [103, 64, 1, 23, 1, 'CLIP'],
    [116, 11, 1, 17, 1, 'CLIP'],
    [117, 11, 0, 17, 0, 'MODEL'],
    [118, 23, 0, 10, 0, 'MODEL'],
    [121, 18, 0, 15, 1, 'VAE'],
    [123, 84, 0, 10, 3, 'LATENT'],
    [126, 88, 0, 13, 0, 'CLIP'],
    [127, 88, 0, 14, 0, 'CLIP'],
    [128, 23, 1, 88, 0, 'CLIP']
  ]
}

const converted = editor.editorToApiGraph(editorWorkflow)

test('editor exports convert to an API graph with bypass passthrough', () => {
  assert.equal(Object.keys(converted.graph).length, 12, 'three bypassed LoRAs are skipped')
  assert.deepEqual(converted.skipped, ['61', '62', '64'])
  assert.ok(converted.notes.some(line => line.includes('bypassed') && line.includes('61, 62, 64')))

  const sampler = converted.graph['10'].inputs
  assert.deepEqual(sampler.model, ['23', 0])
  assert.deepEqual(sampler.positive, ['13', 0])
  assert.deepEqual(sampler.negative, ['14', 0])
  assert.deepEqual(sampler.latent_image, ['84', 0])
  assert.equal(sampler.seed, 981998850141260)
  assert.equal(sampler.steps, 15)
  assert.equal(sampler.cfg, 1.2)
  assert.equal(sampler.sampler_name, 'euler_ancestral')
  assert.equal(sampler.scheduler, 'karras')
  assert.equal(sampler.denoise, 1)
  assert.equal(
    'control_after_generate' in sampler,
    false,
    'UI-only widget never reaches the API graph'
  )

  // 23 sits behind one bypassed LoRA (64), 63 behind two (61 and 62).
  assert.deepEqual(converted.graph['23'].inputs.model, ['63', 0])
  assert.deepEqual(converted.graph['23'].inputs.clip, ['63', 1])
  assert.deepEqual(converted.graph['63'].inputs.model, ['17', 0])
  assert.deepEqual(converted.graph['63'].inputs.clip, ['17', 1])
  assert.deepEqual(converted.graph['17'].inputs.model, ['11', 0])
  assert.deepEqual(converted.graph['17'].inputs.clip, ['11', 1])

  assert.equal(converted.graph['13'].inputs.text, positiveText)
  assert.deepEqual(converted.graph['13'].inputs.clip, ['88', 0])
  assert.equal(converted.graph['14'].inputs.text, negativeText)
  assert.equal(converted.graph['14']._meta.collapsed, true, 'collapsed state survives the import')
  assert.deepEqual(converted.graph['88'].inputs, { stop_at_clip_layer: -2, clip: ['23', 1] })
  assert.deepEqual(converted.graph['15'].inputs, { samples: ['10', 0], vae: ['18', 0] })
  assert.deepEqual(converted.graph['16'].inputs, { filename_prefix: 'ComfyUI', images: ['15', 0] })
  assert.deepEqual(converted.graph['84'].inputs, { width: 1280, height: 1920, batch_size: 1 })
  assert.equal(converted.graph['11'].inputs.ckpt_name, 'IL\\uncannyValley_Noob3dV3.safetensors')
  assert.equal(converted.graph['18'].inputs.vae_name, 'pony_sdxl_vae.safetensors')
  assert.deepEqual(
    converted.graph['10']._meta.pos,
    [1268, -171],
    'editor positions move into _meta'
  )
})

test('suggestBindings maps the converted graph without manual work', () => {
  const suggestion = graphService.suggestBindings(converted.graph)
  assert.deepEqual(suggestion.bindings.prompt, { node_id: '13', input_name: 'text' })
  assert.deepEqual(suggestion.bindings.negative_prompt, { node_id: '14', input_name: 'text' })
  assert.deepEqual(suggestion.bindings.seed, { node_id: '10', input_name: 'seed' })
  assert.deepEqual(suggestion.bindings.width, { node_id: '84', input_name: 'width' })
  assert.deepEqual(suggestion.bindings.height, { node_id: '84', input_name: 'height' })
  assert.equal(suggestion.output_node, '16')
})

test('importWorkflowGraph dispatches by format and parses editor JSON', () => {
  const apiText = JSON.stringify({
    3: {
      class_type: 'KSampler',
      inputs: { seed: 1, steps: 4, cfg: 7, sampler_name: 'euler', scheduler: 'normal', denoise: 1 }
    }
  })
  const apiResult = editor.importWorkflowGraph(apiText)
  assert.equal(Object.keys(apiResult.graph).length, 1)
  assert.deepEqual(apiResult.notes, [])

  const editorResult = editor.importWorkflowGraph(JSON.stringify(editorWorkflow))
  assert.equal(Object.keys(editorResult.graph).length, 12)
  assert.deepEqual(editorResult.skipped, ['61', '62', '64'])

  assert.throws(() => editor.parseEditorWorkflow('not json'), /not valid JSON/)
  assert.throws(() => editor.parseEditorWorkflow(apiText), /ComfyUI editor/)
  assert.throws(
    () =>
      editor.parseEditorWorkflow(
        JSON.stringify({
          nodes: [
            { id: 1, type: 'X' },
            { id: 1, type: 'Y' }
          ],
          links: []
        })
      ),
    /duplicate node ids/
  )
  assert.throws(
    () =>
      editor.parseEditorWorkflow(
        JSON.stringify({
          nodes: [{ id: 1, type: 'X', pos: [0, 0], title: 'n' + 'x'.repeat(300000) }]
        })
      ),
    /256 KiB/
  )
})

test('muted nodes break the chain and widgets never overwrite links', () => {
  const result = editor.editorToApiGraph({
    nodes: [
      {
        id: 1,
        type: 'CheckpointLoaderSimple',
        inputs: [],
        outputs: [
          { name: 'MODEL', type: 'MODEL' },
          { name: 'CLIP', type: 'CLIP' }
        ],
        widgets_values_named: { ckpt_name: 'a.safetensors' }
      },
      {
        id: 2,
        type: 'LoraLoader',
        mode: 2,
        inputs: [
          { name: 'model', type: 'MODEL', link: 5 },
          { name: 'clip', type: 'CLIP', link: 6 }
        ],
        outputs: [
          { name: 'MODEL', type: 'MODEL' },
          { name: 'CLIP', type: 'CLIP' }
        ],
        widgets_values_named: { lora_name: 'b.safetensors', strength_model: 1, strength_clip: 1 }
      },
      {
        id: 3,
        type: 'LoraLoader',
        inputs: [
          { name: 'model', type: 'MODEL', link: 7 },
          { name: 'clip', type: 'CLIP', link: 8 }
        ],
        outputs: [
          { name: 'MODEL', type: 'MODEL' },
          { name: 'CLIP', type: 'CLIP' }
        ],
        widgets_values_named: {
          lora_name: 'c.safetensors',
          strength_model: 0.5,
          strength_clip: 1,
          text: 'stale'
        }
      },
      {
        id: 4,
        type: 'CLIPTextEncode',
        inputs: [{ name: 'clip', type: 'CLIP', link: 9 }],
        outputs: [{ name: 'CONDITIONING', type: 'CONDITIONING' }],
        widgets_values_named: { text: 'hello', control_after_generate: 'fixed' }
      }
    ],
    links: [
      [5, 1, 0, 2, 0, 'MODEL'],
      [6, 1, 1, 2, 1, 'CLIP'],
      [7, 2, 0, 3, 0, 'MODEL'],
      [8, 1, 1, 3, 1, 'CLIP'],
      [9, 1, 1, 4, 0, 'CLIP']
    ]
  })
  assert.equal(result.graph['2'], undefined, 'muted node skipped')
  assert.equal('model' in result.graph['3'].inputs, false, 'muted upstream leaves no model input')
  assert.deepEqual(result.graph['3'].inputs.clip, ['1', 1], 'live links keep resolving')
  assert.equal(result.graph['4'].inputs.text, 'hello')
  assert.equal('control_after_generate' in result.graph['4'].inputs, false)
})

test('legacy positional widgets map for core nodes, unknown nodes raise a note', () => {
  const legacy = editor.editorToApiGraph({
    nodes: [
      {
        id: 7,
        type: 'LoraLoader',
        inputs: [],
        outputs: [],
        widgets_values: ['legacy.safetensors', 0.7, 0.9]
      },
      { id: 8, type: 'MyCustomGadget', inputs: [], outputs: [], widgets_values: ['mystery'] }
    ],
    links: []
  })
  assert.deepEqual(legacy.graph['7'].inputs, {
    lora_name: 'legacy.safetensors',
    strength_model: 0.7,
    strength_clip: 0.9
  })
  assert.deepEqual(legacy.graph['8'].inputs, {})
  assert.ok(legacy.notes.some(line => line.includes('8') && line.includes('named widget values')))
})

test('socket colours follow the ComfyUI palette for core inputs', () => {
  assert.equal(graphService.socketColor('model'), '#b39bdb')
  assert.equal(graphService.socketColor('clip'), '#ffd54f')
  assert.equal(graphService.socketColor('positive'), '#ff8a3c')
  assert.equal(graphService.socketColor('latent_image'), '#ff9e9e')
  assert.equal(graphService.socketColor('images'), '#64b5f6')
  assert.equal(graphService.socketColor('vae'), '#7ee787')
  assert.equal(graphService.socketColor('anything_else'), '#94a3b8')
})

test('server schemas name legacy positional widgets for any node class', () => {
  const schemas = {
    DualCLIPLoader: [
      { name: 'clip_name1', kind: 'combo' },
      { name: 'clip_name2', kind: 'combo' },
      { name: 'type', kind: 'combo' }
    ],
    EmptySD3LatentImage: [
      { name: 'width', kind: 'int' },
      { name: 'height', kind: 'int' },
      { name: 'batch_size', kind: 'int' }
    ],
    MyCustomGadget: [
      { name: 'gadget_name', kind: 'combo' },
      { name: 'model', kind: 'socket' },
      { name: 'strength', kind: 'float' }
    ]
  }
  const result = editor.editorToApiGraph(
    {
      nodes: [
        {
          id: 1,
          type: 'DualCLIPLoader',
          inputs: [],
          outputs: [{ name: 'CLIP', type: 'CLIP' }],
          widgets_values: ['clip_g.safetensors', 'clip_l.safetensors', 'sdxl']
        },
        {
          id: 2,
          type: 'EmptySD3LatentImage',
          inputs: [],
          outputs: [{ name: 'LATENT', type: 'LATENT' }],
          widgets_values: [1024, 1536, 1]
        },
        { id: 3, type: 'MyCustomGadget', inputs: [], outputs: [], widgets_values: ['fancy.safetensors', 0.5] }
      ],
      links: []
    },
    schemas
  )
  assert.deepEqual(result.graph['1'].inputs, {
    clip_name1: 'clip_g.safetensors',
    clip_name2: 'clip_l.safetensors',
    type: 'sdxl'
  })
  assert.deepEqual(result.graph['2'].inputs, { width: 1024, height: 1536, batch_size: 1 })
  assert.deepEqual(result.graph['3'].inputs, { gadget_name: 'fancy.safetensors', strength: 0.5 })
})

test('schema-driven legacy KSampler aligns like the editor, control widget stays UI-only', () => {
  const result = editor.editorToApiGraph(
    {
      nodes: [
        {
          id: 5,
          type: 'KSampler',
          inputs: [],
          outputs: [],
          widgets_values: [123, 'randomize', 15, 1.2, 'euler_ancestral', 'karras', 1]
        }
      ],
      links: []
    },
    {
      KSampler: [
        { name: 'seed', kind: 'int' },
        { name: 'steps', kind: 'int' },
        { name: 'cfg', kind: 'float' },
        { name: 'sampler_name', kind: 'combo' },
        { name: 'scheduler', kind: 'combo' },
        { name: 'denoise', kind: 'float' }
      ]
    }
  )
  assert.deepEqual(result.graph['5'].inputs, {
    seed: 123,
    steps: 15,
    cfg: 1.2,
    sampler_name: 'euler_ancestral',
    scheduler: 'karras',
    denoise: 1
  })
})

test('value-count mismatch against the server schema never guesses', () => {
  const result = editor.editorToApiGraph(
    {
      nodes: [{ id: 9, type: 'OldCustomNode', inputs: [], outputs: [], widgets_values: ['a', 'b'] }],
      links: []
    },
    { OldCustomNode: [{ name: 'only_one', kind: 'combo' }] }
  )
  assert.deepEqual(result.graph['9'].inputs, {})
  assert.ok(result.notes.some(line => line.includes('9') && line.includes('skipped instead of guessing')))
})

test('reroutes pass links through and editor-only nodes never reach the graph', () => {
  const result = editor.editorToApiGraph({
    nodes: [
      {
        id: 1,
        type: 'CheckpointLoaderSimple',
        inputs: [],
        outputs: [{ name: 'MODEL', type: 'MODEL', links: [1] }],
        widgets_values_named: { ckpt_name: 'a.safetensors' }
      },
      {
        id: 2,
        type: 'Reroute',
        inputs: [{ name: '', type: 'MODEL', link: 1 }],
        outputs: [{ name: '', type: 'MODEL', links: [2] }]
      },
      {
        id: 3,
        type: 'Reroute',
        inputs: [{ name: '', type: 'MODEL', link: 2 }],
        outputs: [{ name: '', type: 'MODEL', links: [3] }]
      },
      {
        id: 4,
        type: 'KSampler',
        inputs: [{ name: 'model', type: 'MODEL', link: 3 }],
        outputs: [],
        widgets_values_named: { seed: 1 }
      },
      { id: 5, type: 'Note', inputs: [], outputs: [], widgets_values: ['reminder'] }
    ],
    links: [
      [1, 1, 0, 2, 0, 'MODEL'],
      [2, 2, 0, 3, 0, 'MODEL'],
      [3, 3, 0, 4, 0, 'MODEL']
    ]
  })
  assert.deepEqual(result.graph['4'].inputs.model, ['1', 0], 'two reroutes resolve to the checkpoint')
  assert.equal(result.graph['2'], undefined)
  assert.equal(result.graph['3'], undefined)
  assert.equal(result.graph['5'], undefined)
  assert.ok(result.notes.some(line => line.includes('editor-only') && line.includes('Reroute#2')))
})

test('PrimitiveNode inlines its literal into converted widget inputs', () => {
  const result = editor.editorToApiGraph({
    nodes: [
      {
        id: 1,
        type: 'PrimitiveNode',
        inputs: [],
        outputs: [{ name: 'STRING', type: 'STRING', links: [1] }],
        widgets_values: ['masterpiece', 'fixed']
      },
      {
        id: 2,
        type: 'CLIPTextEncode',
        inputs: [{ name: 'text', type: 'STRING', link: 1 }],
        outputs: [{ name: 'CONDITIONING', type: 'CONDITIONING' }],
        widgets_values: []
      }
    ],
    links: [[1, 1, 0, 2, 0, 'STRING']]
  })
  assert.equal(result.graph['2'].inputs.text, 'masterpiece')
  assert.equal(result.graph['1'], undefined)
})

test('unlinked converted widgets keep their value from the input descriptor', () => {
  const result = editor.editorToApiGraph({
    nodes: [
      {
        id: 1,
        type: 'CLIPTextEncode',
        inputs: [{ name: 'text', type: 'STRING', link: null, widget: { name: 'text', value: 'kept text' } }],
        outputs: [],
        widgets_values: []
      }
    ],
    links: []
  })
  assert.equal(result.graph['1'].inputs.text, 'kept text')
})

test('importWorkflowGraphWithServer enriches from the server and falls back offline', async () => {
  const workflowJson = JSON.stringify({
    nodes: [
      {
        id: 1,
        type: 'DualCLIPLoader',
        inputs: [],
        outputs: [],
        widgets_values: ['g.safetensors', 'l.safetensors', 'sdxl']
      }
    ],
    links: []
  })
  const fetched = []
  const smart = await editor.importWorkflowGraphWithServer(workflowJson, async classes => {
    fetched.push(classes)
    return {
      DualCLIPLoader: [
        { name: 'clip_name1', kind: 'combo' },
        { name: 'clip_name2', kind: 'combo' },
        { name: 'type', kind: 'combo' }
      ]
    }
  })
  assert.deepEqual(fetched, [['DualCLIPLoader']])
  assert.deepEqual(smart.graph['1'].inputs, {
    clip_name1: 'g.safetensors',
    clip_name2: 'l.safetensors',
    type: 'sdxl'
  })

  const offline = await editor.importWorkflowGraphWithServer(workflowJson, async () => {
    throw new Error('server down')
  })
  assert.deepEqual(offline.graph['1'].inputs, {
    clip_name1: 'g.safetensors',
    clip_name2: 'l.safetensors',
    type: 'sdxl'
  })
  assert.ok(offline.notes.some(line => line.includes('not fetched')))

  let apiCalls = 0
  const api = await editor.importWorkflowGraphWithServer(
    JSON.stringify({
      3: {
        class_type: 'KSampler',
        inputs: { seed: 1, steps: 4, cfg: 7, sampler_name: 'euler', scheduler: 'normal', denoise: 1 }
      }
    }),
    async () => {
      apiCalls += 1
      return {}
    }
  )
  assert.equal(apiCalls, 0, 'API-format files never touch the schema endpoint')
  assert.equal(Object.keys(api.graph).length, 1)
})

test('live schemas keep image-loader filenames and omit upload controls', async () => {
  for (const type of ['LoadImage', 'LoadImageMask']) {
    const mask = type === 'LoadImageMask'
    const schema = [{ name: 'image', kind: 'combo' }]
    if (mask) schema.push({ name: 'channel', kind: 'combo' })
    const values = mask ? ['reference.png', 'alpha', 'image'] : ['reference.png', 'image']
    const text = JSON.stringify({ nodes: [{ id: 1, type, widgets_values: values }] })
    const result = await editor.importWorkflowGraphWithServer(text, async () => ({ [type]: schema }))
    const expected = mask ? { image: 'reference.png', channel: 'alpha' } : { image: 'reference.png' }
    assert.deepEqual(result.graph['1'].inputs, expected)
    assert.deepEqual(editor.importWorkflowGraph(text).graph['1'].inputs, expected)
    assert.equal(result.notes.length, 0)
    const withoutButton = JSON.stringify({ nodes: [{ id: 1, type, widgets_values: values.slice(0, -1) }] })
    assert.deepEqual((await editor.importWorkflowGraphWithServer(withoutButton, async () => ({ [type]: schema }))).graph['1'].inputs, expected)
  }
})
