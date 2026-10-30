"""Author preferences survive generated data and do not lock writes during inference."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select

from backend.api.routes.adventures.editing.clothing_settings import apply_clothing_update
from backend.engine.manifest_apply.adventure_meta import apply_final_adventure_fields
from backend.engine.world_generation_persistence import persist_generated_narrative
from backend.models.adventure_template import AdventureTemplate
from backend.models.user import User
from tests.test_clothing_editor_conversion import legacy

__all__ = ["legacy"]


@pytest.mark.parametrize("enabled", [False, True])
async def test_generation_preserves_author_preferences_at_both_save_stages(
    db_session, auth_client, enabled
):
    user = await db_session.scalar(select(User))
    preference = {"enabled": enabled, "level": "soft"}
    adventure = AdventureTemplate(
        id="author-settings",
        title="Quiet room",
        owner_id=user.id,
        rule_enforcement_mode="vn",
        original_manifest={
            "nsfw_settings": deepcopy(preference),
            "clothing_settings": {"detailed": False},
        },
    )
    db_session.add(adventure)
    await db_session.commit()
    generated = {"teaser": "A quiet room.", "scenes": [{"id": "ROOM"}]}
    await persist_generated_narrative(
        db_session, adventure, adventure.id, generated, "A quiet room", "English", None
    )
    await db_session.refresh(adventure)
    assert adventure.original_manifest["scenes"] == generated["scenes"]
    assert adventure.original_manifest["nsfw_settings"] == preference
    # Generated values may not override the author's saved choice either.
    generated["nsfw_settings"] = {"enabled": not enabled, "level": "medium"}
    apply_final_adventure_fields(SimpleNamespace(adventure=adventure, manifest=generated))
    await db_session.commit()
    await db_session.refresh(adventure)
    assert adventure.original_manifest["nsfw_settings"] == preference
    assert adventure.original_manifest["scenes"] == generated["scenes"]


@pytest.mark.parametrize("failure", [False, True])
async def test_combined_editor_save_does_not_flush_before_model(db_session, legacy, failure):
    adventure, _, _, _, llm = legacy
    before = deepcopy(adventure.original_manifest)
    result = llm.aexecute_complex_task.return_value
    flushes = []

    def after_flush(*_args):
        flushes.append(True)

    async def model_reply(*_args, **_kwargs):
        assert not flushes, "A write transaction must not be held while awaiting the model"
        if failure:
            raise RuntimeError("Model unavailable")
        return result

    llm.aexecute_complex_task.side_effect = model_reply
    user = await db_session.scalar(select(User))
    updates = {"nsfw_enabled": True, "nsfw_level": "soft", "detailed_clothing": True}
    event.listen(db_session.sync_session, "after_flush", after_flush)
    try:
        if failure:
            with pytest.raises(HTTPException) as error:
                await apply_clothing_update(db_session, adventure, user, updates)
            assert error.value.status_code == 502
            await db_session.refresh(adventure)
            assert adventure.original_manifest == before
        else:
            await apply_clothing_update(db_session, adventure, user, updates)
            await db_session.commit()
            await db_session.refresh(adventure)
            assert adventure.original_manifest["clothing_settings"]["detailed"] is True
            assert adventure.original_manifest["nsfw_settings"] == {
                "enabled": True,
                "level": "soft",
            }
            assert updates == {}
    finally:
        event.remove(db_session.sync_session, "after_flush", after_flush)
    llm.aexecute_complex_task.assert_awaited_once()
