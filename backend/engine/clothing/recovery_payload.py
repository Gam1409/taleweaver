"""Compact model-facing facts; budget history by complete messages, never clipped quotes."""

import json
from typing import Any

from backend.engine.clothing.profiles import garment_for_item
from backend.engine.clothing.recovery_contract import existing_body_items, existing_garments
from backend.engine.clothing.recovery_mentions import explicit_mentions

MAX_PAYLOAD = 64000


def _facts(context: dict, detailed: bool) -> dict:
    actor = context["actor"]
    snapshot = context["snapshot"]
    eligible = existing_garments(context)
    canonical: dict[str, dict[str, Any]] = {
        key: {"name": item.get("name", key)} for key, item in snapshot.items.items()
    }
    for key, item in eligible.items():
        garment = garment_for_item(item)
        canonical[key]["clothing"] = garment.model_dump() if garment else None
    profile = actor.get("visual_profile")
    worn = profile.get("worn", []) if isinstance(profile, dict) else []
    return {
        "target_actor": {
            "id": actor["id"],
            "name": actor.get("name", ""),
            "age_years": actor.get("age_years"),
            "worn_item_ids": [
                row["item_id"] for row in worn if isinstance(row, dict) and "item_id" in row
            ],
            "worn_placements": {
                row["item_id"]: row.get("uncovered_regions", [])
                for row in worn
                if isinstance(row, dict) and "item_id" in row
            },
            "body_placements": {
                row["item_id"]: row["attachment_slot"]
                for row in worn
                if isinstance(row, dict) and row.get("attachment_slot") and row.get("item_id")
            },
            "body": profile.get("body") if isinstance(profile, dict) else None,
        },
        "canonical_items": canonical,
        "owners": snapshot.owners,
        "existing_garments": list(eligible),
        "existing_body_items": list(existing_body_items(context)),
        "detailed_clothing": detailed,
        "player_sources_require_confirmation": context.get("allow_player_sources", False),
    }


def build_payload(context: dict, detailed: bool) -> tuple[dict, str]:
    compact = _facts(context, detailed)
    messages = list(context["messages"])
    while True:
        selected = {
            **context,
            "messages": messages,
            "limited": context["limited"] or len(messages) < len(context["messages"]),
        }
        payload = json.dumps(
            {
                **compact,
                "history": messages,
                "explicit_garment_mentions": explicit_mentions(selected),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(payload) <= MAX_PAYLOAD:
            if context["messages"] and not messages:
                raise ValueError(
                    "No complete recent narration fits beside the compact item catalogue. No model request was sent."
                )
            return selected, payload
        if not messages:
            raise ValueError(
                "The compact item catalogue exceeds the recovery budget even without history. No model request was sent."
            )
        messages = messages[1:]
