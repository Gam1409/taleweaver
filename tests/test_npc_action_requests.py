"""World-action requests stay small and cannot supply actor authority or replacement state."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backend.engine.npc_actions.contracts import ActionRequest


@pytest.mark.parametrize(
    "packet",
    [
        {"tool": "move_to", "destination_scene_id": "PORCH"},
        {"tool": "take_item", "item_id": "COMPASS"},
        {"tool": "put_down_item", "item_id": "COMPASS", "position": "on the bench"},
        {"tool": "give_item", "item_id": "COMPASS", "recipient_id": "@player"},
        {"tool": "wear_item", "item_id": "COAT"},
        {"tool": "take_off_item", "item_id": "COAT"},
        {"tool": "adjust_clothing", "item_id": "COAT", "uncovered_regions": ["arms"]},
        {
            "tool": "change_item_state",
            "item_id": "COAT",
            "dimension": "damage",
            "detail": "A torn cuff.",
        },
        {"tool": "use_item", "item_id": "FLASK", "extent": "partial"},
        {"tool": "use_item", "item_id": "RATION", "extent": "full"},
        {"tool": "discard_actions"},
    ],
)
def test_supported_operations_do_not_require_a_world_state_document(packet):
    parsed = TypeAdapter(ActionRequest).validate_python(packet)
    actual = parsed.model_dump(exclude_none=True)
    assert all(actual[key] == value for key, value in packet.items())


@pytest.mark.parametrize(
    "packet",
    [
        {"tool": "take_item", "item_id": "COMPASS", "actor_id": "other"},
        {"tool": "move_to", "destination_scene_id": "PORCH", "session_id": "foreign"},
        {"tool": "wear_item", "item_id": "COAT", "inventory": []},
        {
            "tool": "change_item_state",
            "item_id": "COAT",
            "dimension": "damage",
            "detail": "x" * 321,
        },
        {"tool": "adjust_clothing", "item_id": "COAT", "uncovered_regions": ["arms", "arms"]},
        {"tool": "take_item", "item_id": ""},
        {"tool": "use_item", "item_id": "RATION", "extent": "unlimited"},
        {"tool": "run_code", "code": "arbitrary source"},
    ],
)
def test_invalid_requests_do_not_grant_implicit_host_authority(packet):
    with pytest.raises(ValidationError):
        TypeAdapter(ActionRequest).validate_python(packet)
