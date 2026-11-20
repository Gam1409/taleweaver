"""Public placement must not replace canonical physical custody with legal ownership."""

from backend.engine.chpm.observable_state import project
from tests.observable_state_support import observation, world


def test_loose_object_preserves_scene_custody_even_when_it_has_a_property_owner():
    host, rows = world()
    item = next(row for row in rows if row.id == "KEY")
    item.metadata_json = {"property_owner_id": "other"}
    item.spatial_position = "on the bench"
    visible = project(host, rows, "npc", observation()).entities["KEY"]
    assert visible["owner_id"] == "__scene__"
    assert visible["spatial_position"] == "on the bench"


def test_canonical_loose_position_is_visible_without_an_extra_placement_record():
    host, rows = world()
    next(row for row in rows if row.id == "KEY").spatial_position = "on the bench"
    visible = project(host, rows, "npc", observation()).entities["KEY"]
    assert visible["owner_id"] == "__scene__"
    assert visible["spatial_position"] == "on the bench"
