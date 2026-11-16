# TaleWeaver Entity Bundle (`.twe`)

A `.twe` file transfers a single **protagonist**, **NPC**, or **item** between adventures, including its image. Like `.adz`, it is a plain ZIP archive.

## Layout

```
entity.json         # manifest (required)
assets/image.<ext>  # optional image (png, jpg, webp)
```

## `entity.json`

```json
{
  "format": "TaleWeaverEntity",
  "version": 1,
  "kind": "npc",
  "exported_at": "2026-10-18T12:00:00+00:00",
  "source": { "adventure_title": "The Alchemist's Folly" },
  "entity": { "id": "OLD_LIBRARIAN", "name": "Old Librarian", "description": "...", "hp": 40 },
  "image": "assets/image.png"
}
```

| Field    | Description |
|----------|-------------|
| `kind`   | `protagonist`, `npc`, or `item`. |
| `entity` | NPC/item: the supported `WorldEntity` transfer fields, excluding database scope, timestamps and image location; the authored `id` is included as a suggested new key. Protagonist: profile, vitals, attributes, `stats` (incl. scripts and special actions), and `status_effects`. |
| `image`  | Path of the image entry inside the ZIP, or `null`. |

## Import Behaviour

These owner-authorized editor endpoints operate on templates, not a live session:

`GET /api/adventures/{id}/editor/transfer/protagonist`, `GET /api/adventures/{id}/editor/transfer/entity/{entity_id}`, `POST /api/adventures/{id}/editor/transfer/import`.

- **NPC / item**: always created as a new entity. The suggested key is normalized to uppercase ASCII letters/digits/underscores and a 30-character bound; on a clash a suffix is added (`SWORD` → `SWORD_2`). If the original scene does not exist, the entity is placed in the start scene. References to scenes/items that do not exist in the target adventure (`allowed_scenes`, `inventory`, `reveals_item_id`) are removed; missing crafting ingredients are only reported. All adjustments are returned as `warnings`.
- **Protagonist**: replaces the supported profile and stats; a bundled image replaces the portrait, while an absent image keeps it. Inventory and equipment stay unchanged, as they reference adventure-specific items.
- Images are checked with Pillow and must be PNG, JPEG, or WEBP. Limits: 25 MiB per bundle, 20 MiB per entry, a 1 MiB manifest, at most 8 entries and a 100:1 compression ratio.

Opaque metadata, including an NPC's portable `agent_runtime` seed, is data rather
than activation. Transfer sanitizes known world references; it does not migrate
arbitrary third-party references inside opaque namespaces. Review copied seed
relationships against the target adventure before activation or public-copy
preparation. See the [runtime contract](agent_runtime.md).

The format owner is [`entity_bundle.py`](../../backend/engine/entity_bundle.py);
template mapping and reference warnings live in
[`entity_transfer_service.py`](../../backend/api/routes/adventures/entity_transfer_service.py).
