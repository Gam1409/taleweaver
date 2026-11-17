"""An optional portable envelope never substitutes for RPG's exactly-one owner check."""

import pytest

from backend.engine.chpm.schema import Usage
from backend.engine.gameplay.combat.ability_choices import prepare
from tests.combat_boundary_support import combat_world
from tests.test_npc_ability_port import ScriptModel, bound, call, turn

__all__ = ["combat_world"]


class StructuredAbilityModel(ScriptModel):
    provider = "custom_openai"
    custom_response_format = "json_schema"

    def __init__(self, *replies):
        super().__init__(*replies)
        self.formats = []

    async def aexecute_simple_task(
        self, system, payload, model, *, response_format=None, single_attempt=False, **kwargs
    ):
        assert single_attempt is True
        self.formats.append(response_format)
        return await super().aexecute_simple_task(system, payload, model, **kwargs)


@pytest.mark.parametrize("invalid", [turn(), turn(call(), call("keep_default", {}, "second"))])
async def test_rpg_rejects_empty_or_multiple_choices_even_when_a_server_ignores_its_schema(
    combat_world, invalid
):
    model = StructuredAbilityModel(invalid, turn(call("keep_default", {}, "corrected")))
    usage = Usage()
    combat, selector = await bound(combat_world, model, "json", usage=usage)

    assert await selector(await prepare(combat_world.manager.combat, combat, "GUARD")) is None

    assert len(model.calls) == usage.calls == 2
    assert all(value["type"] == "json_schema" for value in model.formats)
    assert combat_world.avatar.hp == 100
    assert combat["enemies"][0]["mana"] == 100
