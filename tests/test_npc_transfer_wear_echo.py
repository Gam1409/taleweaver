"""A carried transfer never supplies the receiving actor's separate wear authority."""

import pytest

from backend.engine.narrated_items.schema import ItemExtraction
from backend.engine.npc_actions.reconciliation import protect
from tests.test_npc_command_reconciliation import action, manager


@pytest.mark.parametrize("recipient", ["other", "__player__"])
@pytest.mark.parametrize("regions", [None, [], ["arms"]])
def test_transfer_does_not_silently_echo_worn_state_or_coverage(recipient, regions):
    host = manager(
        {
            "npc": [
                {
                    "status": "applied",
                    "effect": {
                        "item_id": "COAT",
                        "source_owner": "npc",
                        "destination_owner": recipient,
                        "disposition": "carried",
                    },
                }
            ]
        }
    )
    extracted = ItemExtraction(
        actions=[
            {
                **action("COAT", "npc", recipient),
                "disposition": "worn",
                "uncovered_regions": regions,
            }
        ]
    )

    guarded, _, errors = protect(host, extracted)

    assert not guarded.actions and errors
    assert extracted.actions[0].disposition == "worn"


@pytest.mark.parametrize("regions", [None, [], ["arms"]])
def test_lawful_separate_recipient_wear_can_explain_the_combined_narrated_transfer(regions):
    host = manager(
        {
            "npc": [
                {
                    "status": "applied",
                    "effect": {
                        "item_id": "COAT",
                        "source_owner": "npc",
                        "destination_owner": "other",
                        "disposition": "carried",
                    },
                }
            ],
            "other": [
                {
                    "status": "applied",
                    "effect": {
                        "item_id": "COAT",
                        "operation": "wear",
                        "uncovered_regions": regions or [],
                    },
                }
            ],
        }
    )
    extracted = ItemExtraction(
        actions=[
            {
                **action("COAT", "npc", "other"),
                "disposition": "worn",
                "uncovered_regions": regions,
            }
        ]
    )

    guarded, _, errors = protect(host, extracted)

    assert not guarded.actions and not errors


@pytest.mark.parametrize("wearer", ["npc", "other"])
def test_earlier_wear_does_not_authorize_wearing_after_a_later_transfer(wearer):
    rows = {
        wearer: [
            {
                "status": "applied",
                "effect": {"item_id": "COAT", "operation": "wear", "uncovered_regions": []},
            },
            {
                "status": "applied",
                "effect": {"item_id": "COAT", "operation": "remove", "uncovered_regions": []},
            },
        ],
    }
    rows.setdefault("npc", []).append(
        {
            "status": "applied",
            "effect": {
                "item_id": "COAT",
                "source_owner": "npc",
                "destination_owner": "other",
                "disposition": "carried",
            },
        }
    )
    host = manager(rows)
    extracted = ItemExtraction(actions=[{**action("COAT", "npc", "other"), "disposition": "worn"}])

    guarded, _, errors = protect(host, extracted)

    assert not guarded.actions and errors


def test_blocked_rows_do_not_shortcut_the_later_lawful_wear_window():
    host = manager(
        {
            "npc": [
                {"status": "blocked", "effect": {}},
                {
                    "status": "applied",
                    "effect": {
                        "item_id": "COAT",
                        "source_owner": "npc",
                        "destination_owner": "other",
                        "disposition": "carried",
                    },
                },
            ],
            "other": [
                {
                    "status": "applied",
                    "effect": {"item_id": "COAT", "operation": "wear", "uncovered_regions": []},
                }
            ],
        }
    )
    extracted = ItemExtraction(actions=[{**action("COAT", "npc", "other"), "disposition": "worn"}])

    guarded, _, errors = protect(host, extracted)

    assert not guarded.actions and not errors
