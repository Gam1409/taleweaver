"""Host-built item commands use current custody, not proposed replacement inventories."""

from copy import deepcopy

import pytest

from backend.engine.clothing.context import actor_records
from backend.engine.narrated_items.commands import transfer
from backend.engine.visual_novel.continuity import possession_snapshot
from tests.observable_state_support import world


def fixture():
    host, rows = world()
    return actor_records(host, rows), possession_snapshot(host, rows)


def test_take_and_give_preserve_the_canonical_id_and_intrinsic_metadata():
    actors, possessions = fixture()
    original = deepcopy(actors), deepcopy(possessions)
    item = deepcopy(possessions.items["KEY"])
    taken, snapshot, receipt = transfer(actors, possessions, "npc", "KEY", "take", detailed=False)
    assert actors == original[0] and possessions == original[1]
    assert snapshot.owners["KEY"] == "npc" and receipt["item"]["id"] == "KEY"
    assert next(row for row in taken["npc"]["resolved_inventory"] if row["id"] == "KEY") == item
    given, end, receipt = transfer(
        taken, snapshot, "npc", "KEY", "give", recipient_id="other", detailed=False
    )
    assert end.owners["KEY"] == "other"
    assert not any(row["id"] == "KEY" for row in given["npc"]["resolved_inventory"])
    assert next(row for row in given["other"]["resolved_inventory"] if row["id"] == "KEY") == item


def test_a_second_npc_cannot_take_the_same_scene_item_after_the_first_acquired_it():
    actors, possessions = fixture()
    taken, snapshot, _ = transfer(actors, possessions, "npc", "KEY", "take", detailed=False)
    before = deepcopy(taken), deepcopy(snapshot)
    with pytest.raises(ValueError):
        transfer(taken, snapshot, "other", "KEY", "take", detailed=False)
    assert (taken, snapshot) == before


@pytest.mark.parametrize(
    "item", ["OTHER_COAT", "OTHER_BAG_SECRET", "HIDDEN", "AWAY", "BELL", "invented"]
)
def test_take_cannot_bypass_another_owner_visibility_or_portability(item):
    actors, snapshot = fixture()
    before = deepcopy(actors), deepcopy(snapshot)
    with pytest.raises(ValueError):
        transfer(actors, snapshot, "npc", item, "take", detailed=False)
    assert (actors, snapshot) == before


def test_giving_a_known_worn_item_requires_taking_it_off_first():
    actors, snapshot = fixture()
    with pytest.raises(ValueError, match="worn"):
        transfer(actors, snapshot, "npc", "COAT", "give", recipient_id="other", detailed=False)


def test_putting_down_a_possession_keeps_identity_and_records_only_requested_position():
    actors, snapshot = fixture()
    changed, final, receipt = transfer(
        actors, snapshot, "npc", "FLASK", "put_down", position="on the bench", detailed=False
    )
    assert final.owners["FLASK"] == "__scene__"
    assert final.items["FLASK"]["spatial_position"] == "on the bench"
    assert not any(row["id"] == "FLASK" for row in changed["npc"]["resolved_inventory"])
    assert receipt["destination_owner"] == "__scene__" and receipt["item"]["id"] == "FLASK"
