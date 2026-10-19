<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import type { CatalogTile } from '@/types'

const props = withDefaults(defineProps<{
  isOpen: boolean
  isEditingExisting: boolean
  item: CatalogTile
  index: number | null
  type: 'styles' | 'tones'
  isGenerating?: boolean
  isSubmitting?: boolean
}>(), {
  isGenerating: false,
  isSubmitting: false,
})

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', item: CatalogTile): void
  (e: 'generate', payload: { type: 'styles' | 'tones', item: CatalogTile, index: number | null, prompt?: string | null }): void
  (e: 'upload', payload: { event: Event, type: 'styles' | 'tones', item: CatalogTile, index: number | null }): void
}>()

const editingItem = ref<CatalogTile>({ ...props.item })
const showCustomPrompt = ref(false)
const customPromptInput = ref('')

watch(() => props.item, (newItem) => {
  editingItem.value = JSON.parse(JSON.stringify(newItem))
  showCustomPrompt.value = false
  customPromptInput.value = ''
}, { deep: true })

const typeSingular = computed(() => {
  return props.type === 'styles' ? 'Image Style' : 'Narrative Tone'
})

const triggerFileUpload = () => {
  const input = document.getElementById('modal-upload') as HTMLInputElement
  input?.click()
}

const handleSave = () => {
  if (!editingItem.value.name.trim()) return
  // Auto-generate ID from name if blank
  if (!editingItem.value.id.trim()) {
    editingItem.value.id = editingItem.value.name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
  }
  emit('save', editingItem.value)
}

const handleQuickGenerate = () => {
  emit('generate', { 
    type: props.type, 
    item: editingItem.value, 
    index: props.index,
    prompt: null
  })
}

const handleCustomGenerate = () => {
  if (!customPromptInput.value.trim()) return
  emit('generate', { 
    type: props.type, 
    item: editingItem.value, 
    index: props.index,
    prompt: customPromptInput.value.trim()
  })
}

const handleUpload = (event: Event) => {
  emit('upload', { event, type: props.type, item: editingItem.value, index: props.index })
}

const removeImage = () => {
  editingItem.value.image_url = ''
}
</script>

<template>
  <Teleport to="body">
    <div v-if="isOpen" class="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <!-- Backdrop -->
      <div class="absolute inset-0 bg-black/85 backdrop-blur-sm" @click="emit('close')"></div>

      <!-- Modal Card -->
      <div class="relative w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-3xl shadow-2xl p-6 sm:p-8 animate-fade-in max-h-[90vh] overflow-y-auto custom-scrollbar">
        <!-- Modal Header -->
        <div class="flex items-center justify-between pb-4 mb-6 border-b border-slate-800">
          <div class="flex items-center gap-3">
            <div 
              class="w-10 h-10 rounded-xl flex items-center justify-center text-lg"
              :class="type === 'styles' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20'"
            >
              <i :class="type === 'styles' ? 'ra ra-paint-brush' : 'ra ra-scroll'"></i>
            </div>
            <div>
              <h2 class="text-xl font-bold text-white">
                {{ isEditingExisting ? 'Edit' : 'Create' }} {{ typeSingular }}
              </h2>
              <p class="text-xs text-slate-400">
                {{ type === 'styles' ? 'Configure visual rendering aesthetic & artwork.' : 'Configure atmospheric tone, world voice & narrative mood.' }}
              </p>
            </div>
          </div>
          <button @click="emit('close')" class="p-1.5 text-slate-500 hover:text-white rounded-lg transition-colors">
            <i class="ra ra-cancel text-sm"></i>
          </button>
        </div>

        <!-- Cover Art & Actions Row -->
        <div class="mb-6 p-4 bg-slate-950/70 border border-slate-800 rounded-2xl flex flex-col sm:flex-row items-center gap-5">
          <!-- Thumbnail Preview -->
          <div class="w-28 h-28 rounded-2xl overflow-hidden bg-slate-900 border border-slate-800 flex-shrink-0 relative group shadow-md">
            <img v-if="editingItem.image_url" :src="editingItem.image_url" class="w-full h-full object-cover" />
            <div v-else class="w-full h-full flex flex-col items-center justify-center bg-slate-900/80 text-slate-700">
              <i :class="[type === 'styles' ? 'ra ra-paint-brush' : 'ra ra-scroll', 'text-2xl mb-1 opacity-40']"></i>
              <span class="text-[9px] uppercase font-bold tracking-wider opacity-50">No Cover Art</span>
            </div>

            <!-- Loading overlay -->
            <div v-if="isGenerating" class="absolute inset-0 bg-black/75 flex flex-col items-center justify-center gap-1.5 text-emerald-400 text-xs">
              <div class="w-6 h-6 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin"></div>
              <span class="text-[9px] font-mono font-bold tracking-wider">Generating...</span>
            </div>

            <!-- Remove Button if image present -->
            <button 
              v-if="editingItem.image_url && !isGenerating"
              @click="removeImage"
              type="button"
              class="absolute top-1.5 right-1.5 p-1 bg-black/70 hover:bg-rose-600 text-white rounded-md opacity-0 group-hover:opacity-100 transition-all text-xs"
              title="Remove Cover Image"
            >
              <i class="ra ra-cancel"></i>
            </button>
          </div>

          <!-- Action Buttons -->
          <div class="flex flex-col gap-2 w-full">
            <div class="flex items-center justify-between text-xs font-bold text-slate-400">
              <span>Catalog Cover Tile Art</span>
              <span v-if="editingItem.image_url" class="text-emerald-400 font-mono text-[10px]">✓ Custom Artwork Set</span>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <button 
                type="button"
                @click="handleQuickGenerate" 
                :disabled="!editingItem.name || isGenerating"
                class="flex items-center justify-center gap-1.5 px-3 py-2 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border border-emerald-500/30 text-xs font-bold rounded-xl transition-all disabled:opacity-40"
                title="Automatically generate an icon based on the title & description"
              >
                <i class="ra ra-cycle" :class="{'animate-spin': isGenerating}"></i>
                <span>Auto AI Image</span>
              </button>

              <button 
                type="button"
                @click="showCustomPrompt = !showCustomPrompt"
                :disabled="isGenerating"
                class="flex items-center justify-center gap-1.5 px-3 py-2 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/30 text-xs font-bold rounded-xl transition-all"
              >
                <i class="ra ra-quill-ink"></i>
                <span>Custom Prompt</span>
              </button>

              <button 
                type="button"
                @click="triggerFileUpload"
                class="flex items-center justify-center gap-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 text-xs font-bold rounded-xl transition-all"
              >
                <i class="ra ra-camera"></i>
                <span>Upload File</span>
              </button>
              <input id="modal-upload" type="file" class="hidden" accept="image/*" @change="handleUpload" />
            </div>

            <!-- Custom Prompt Drawer -->
            <div v-if="showCustomPrompt" class="mt-2 p-3 bg-slate-900 border border-slate-800 rounded-xl space-y-2 animate-fade-in">
              <div class="flex items-center justify-between">
                <span class="text-[11px] font-bold text-slate-400">Custom Image Prompt:</span>
                <button 
                  type="button"
                  @click="handleCustomGenerate"
                  :disabled="!customPromptInput.trim() || isGenerating"
                  class="px-2.5 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold disabled:opacity-40 flex items-center gap-1"
                >
                  <i class="ra ra-cycle"></i> Generate
                </button>
              </div>
              <input 
                v-model="customPromptInput"
                type="text"
                placeholder="e.g. Dark gothic oil painting with volumetric mist and muted amber candlelight..."
                class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white placeholder-slate-600 outline-none focus:ring-1 focus:ring-blue-500"
                @keydown.enter="customPromptInput.trim() && handleCustomGenerate()"
              />
            </div>
          </div>
        </div>

        <!-- Form Inputs -->
        <div class="space-y-4">
          <!-- Display Name -->
          <div>
            <div class="flex justify-between items-center mb-1.5">
              <label class="block text-xs font-bold text-slate-400 uppercase tracking-wider">
                Display Name <span class="text-rose-400">*</span>
              </label>
              <span class="text-[10px] font-mono text-slate-500">{{ (editingItem.name || '').length }} / 30</span>
            </div>
            <input 
              v-model="editingItem.name" 
              type="text" 
              maxlength="30" 
              placeholder="e.g. Grim Dark Fantasy" 
              class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-white text-sm focus:ring-2 focus:ring-emerald-500/50 outline-none" 
            />
          </div>

          <!-- Description -->
          <div>
            <div class="flex justify-between items-center mb-1.5">
              <label class="block text-xs font-bold text-slate-400 uppercase tracking-wider">
                Short Description
              </label>
              <span class="text-[10px] font-mono text-slate-500">{{ (editingItem.description || '').length }} / 200</span>
            </div>
            <textarea 
              v-model="editingItem.description" 
              rows="2" 
              maxlength="200" 
              placeholder="A brief summary shown to players in the adventure creator."
              class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2 text-white text-xs focus:ring-2 focus:ring-emerald-500/50 outline-none resize-none leading-relaxed"
            ></textarea>
          </div>

          <!-- System Instruction / Style Prefix -->
          <div>
            <div class="flex justify-between items-center mb-1.5">
              <label class="block text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                <span>System Directive & Style Prompt</span>
                <span class="text-[10px] font-normal lowercase text-slate-500">(injected into generation)</span>
              </label>
              <span class="text-[10px] font-mono text-slate-500">{{ (editingItem.instruction || '').length }} / 500</span>
            </div>
            <textarea 
              v-model="editingItem.instruction" 
              rows="3" 
              maxlength="500" 
              placeholder="Detailed instructions prepended to the AI prompt (e.g. cinematic lighting, chiaroscuro, heavy ink lines, gritty realism...)"
              class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2 text-white text-xs font-mono focus:ring-2 focus:ring-emerald-500/50 outline-none resize-none leading-relaxed"
            ></textarea>
          </div>
        </div>

        <!-- Modal Actions Footer -->
        <div class="mt-8 pt-4 border-t border-slate-800 flex items-center justify-end gap-3">
          <button 
            type="button" 
            @click="emit('close')" 
            class="px-5 py-2.5 rounded-xl border border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800 text-xs font-bold transition-all"
          >
            Cancel
          </button>
          <button 
            type="button" 
            @click="handleSave" 
            :disabled="!editingItem.name.trim() || isSubmitting"
            class="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-bold transition-all shadow-lg shadow-emerald-900/20 disabled:opacity-50 flex items-center gap-2 cursor-pointer"
          >
            <i v-if="isSubmitting" class="ra ra-cycle animate-spin"></i>
            <i v-else class="ra ra-save"></i>
            <span>{{ isSubmitting ? 'Saving...' : 'Save Catalog Entry' }}</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.animate-fade-in {
  animation: fadeIn 0.3s ease-out;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
