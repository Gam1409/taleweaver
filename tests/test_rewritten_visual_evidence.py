"""Rewording prose cannot preserve message-local actions as confirmed visual facts."""

from copy import deepcopy
from types import SimpleNamespace

from backend.api.routes.adventures.regeneration_state import refresh_visual_snapshot
from backend.engine.scene_illustrations.snapshots import REGISTRY_KEY, registry_of


def test_rewrite_retracts_message_local_acts_without_changing_the_frozen_clothing():
    people = [{"id": "NPC", "clothing": "Blue coat", "posture": "standing"}]
    current = SimpleNamespace(
        entity_states={
            REGISTRY_KEY: {
                "snapshots": {
                    "reply": {
                        "nonce": "old",
                        "narration": "Lina kisses Hero.",
                        "visible_facts": {
                            "characters": deepcopy(people),
                            "staging_status": "ready",
                            "explicit": [
                                {
                                    "category": "kissing",
                                    "participants": ["NPC", "hero"],
                                    "evidence": "Lina kisses Hero.",
                                }
                            ],
                        },
                    }
                },
                "images": {"reply": {"url": "/existing-image.png"}},
            }
        }
    )
    message = SimpleNamespace(
        id="reply",
        revision_id="new",
        scene_id="room",
        sequence_id=None,
        content="Lina finishes her reply.",
    )
    refresh_visual_snapshot(current, message)
    registry = registry_of(current.entity_states)
    snapshot = registry["snapshots"]["reply"]
    facts = snapshot["visible_facts"]
    assert not facts.get("explicit")
    assert facts["characters"] == [{"id": "NPC", "clothing": "Blue coat"}]
    assert facts["staging_status"] == "unconfirmed"
    assert snapshot["nonce"] != "old"
    assert snapshot["narration"] == message.content
    assert not registry["images"]
