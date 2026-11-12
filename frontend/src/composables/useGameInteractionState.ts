import { computed, ref, watch, type Ref } from 'vue'
import { resolveNpc, resolveNpcMetadata } from '@/utils/npcIdentity'
import { gameCommandService } from '@/services/gameCommandService'
import { isConsumableEntity } from '@/services/hoverEntityService'
import { useGameHoverTooltip } from './useGameHoverTooltip'

type ContextMenuState = {
  x: number
  y: number
  items: any[]
  title: string
} | null

type UseGameInteractionStateOptions = {
  isActionInputBlocked: Ref<boolean>
  npcMetadata: Ref<Record<string, any>>
  npcEntities?: Ref<any[]>
  playerSheet?: Ref<any>
  handlePlayerInput: (content: string) => Promise<void>
  onAction?: () => void
  onDirectAction?: (action: string) => boolean
}

export function useGameInteractionState(options: UseGameInteractionStateOptions) {
  const {
    isActionInputBlocked,
    npcMetadata,
    npcEntities,
    playerSheet,
    handlePlayerInput,
    onAction,
    onDirectAction,
  } = options

  const hover = useGameHoverTooltip()
  const { hoveredEntity, tooltipImageFailed, handleHover } = hover
  const contextMenu = ref<ContextMenuState>(null)
  const isConsumableHover = computed(() => isConsumableEntity(hoveredEntity.value))

  const handleChatNpcHover = (name: string, event: MouseEvent) => {
    const normalizedName = String(name || '').trim().toLowerCase()
    if (!normalizedName) return

    const sheet = playerSheet?.value
    if (sheet) {
      const sheetName = String(sheet.name || '').trim().toLowerCase()
      if (normalizedName === 'you' || normalizedName === sheetName || normalizedName === `you (${sheetName})`) {
        const playerEntity = {
          id: 'PLAYER',
          name: sheet.name ? `You (${sheet.name})` : 'You',
          entity_type: 'NPC',
          description: sheet.description || 'Your hero character.',
          image_url: sheet.profile_image || null,
          role: sheet.role || 'Hero',
          hp: sheet.hp,
          max_hp: sheet.max_hp,
          mana: sheet.mana,
          max_mana: sheet.max_mana,
          stamina: sheet.stamina,
          max_stamina: sheet.max_stamina,
          inventory: sheet.inventory || [],
          stats: sheet.stats,
        }
        handleHover(playerEntity, event)
        return
      }
    }

    const resolved = resolveNpc(name, npcEntities?.value || [], npcMetadata.value)
    const fromEntities = resolved && (npcEntities?.value || []).find(entity => entity.id === resolved.id)
    const metadata = resolved && resolveNpcMetadata(resolved.id, npcMetadata.value)
    const mergedNpc = fromEntities
      ? { ...(metadata || {}), ...fromEntities, entity_type: 'NPC' }
      : metadata ? { ...metadata, entity_type: 'NPC' } : resolved || { name, entity_type: 'NPC' }

    handleHover(mergedNpc, event)
  }

  const onTooltipImageError = (): void => {
    tooltipImageFailed.value = true
  }

  const openContextMenu = (entity: any, event: MouseEvent) => {
    if (isActionInputBlocked.value) return

    const menu = gameCommandService.buildContextMenu(entity)
    if (!menu) return

    contextMenu.value = {
      x: event.clientX,
      y: event.clientY,
      items: menu.items,
      title: menu.title,
    }

    hover.closeHover()
  }

  const openInventoryContextMenu = (item: any, event: MouseEvent) => {
    if (isActionInputBlocked.value) return

    const menu = gameCommandService.buildInventoryContextMenu(item)
    if (!menu) return

    contextMenu.value = {
      x: event.clientX,
      y: event.clientY,
      items: menu.items,
      title: menu.title,
    }

    hover.closeHover()
  }

  const handleMenuSelect = async (item: any) => {
    if (isActionInputBlocked.value) return
    const action = item.action
    contextMenu.value = null

    if (typeof action === 'string' && onDirectAction?.(action)) {
      return
    }

    if (onAction) onAction()
    await handlePlayerInput(action)
  }

  watch(() => hoveredEntity.value?.image_url, () => {
    tooltipImageFailed.value = false
  })

  return {
    ...hover,
    contextMenu,
    isConsumableHover,
    handleHover,
    handleChatNpcHover,
    onTooltipImageError,
    openContextMenu,
    openInventoryContextMenu,
    handleMenuSelect,
  }
}
