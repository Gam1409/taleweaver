"""Outfit generation exposes known IDs and server-created identities in its wire schema."""

import pytest
from pydantic import ValidationError

from backend.schemas.character_outfits import CharacterOutfitDraft, response_schema
from tests.test_editor_character_outfits import BRA, COAT, SKIRT, fake, seed


async def test_outfit_wire_ids_are_bound_to_the_owned_garments(auth_client, monkeypatch):
    template, actor_id = await seed("npc")
    call = fake(monkeypatch, {"outfit": [SKIRT]})
    response = await auth_client.post(
        f"/api/adventures/{template}/editor/generate-character-outfit",
        json={"target_type": "npc", "target_id": actor_id},
    )
    assert response.status_code == 200, response.text
    model = call.call_args.kwargs["response_model"]
    model.model_validate({"outfit": [SKIRT, BRA, COAT]})
    with pytest.raises(ValidationError):
        model.model_validate({"outfit": [{**SKIRT, "item_id": "MODEL_INVENTED_ID"}]})
    assert "item_id must be null" in call.call_args.kwargs["system_prompt"]


def test_empty_and_independent_wardrobes_do_not_share_identifier_schemas():
    first = response_schema([{"id": "COAT"}])
    second = response_schema([{"id": "BRA"}])
    empty = response_schema([])
    assert empty.model_validate({"outfit": [SKIRT]}).outfit[0].item_id is None
    first.model_validate({"outfit": [COAT]})
    second.model_validate({"outfit": [BRA]})
    with pytest.raises(ValidationError):
        first.model_validate({"outfit": [BRA]})
    with pytest.raises(ValidationError):
        empty.model_validate({"outfit": [COAT]})
    CharacterOutfitDraft.model_validate({"outfit": [BRA, COAT, SKIRT]})
