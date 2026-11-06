"""Shared adventure-image request contracts."""

from typing import Literal, Optional

from pydantic import BaseModel


class RegenerateVisualRequest(BaseModel):
    target_type: Literal["cover", "scene", "npc", "object", "protagonist"]
    target_id: str
    prompt: Optional[str] = None
    use_advanced_model: Optional[bool] = None
    use_current_image: bool = False


class SuggestPromptRequest(BaseModel):
    target_type: Literal["cover", "scene", "npc", "object", "protagonist"]
    target_id: str
    use_advanced_model: Optional[bool] = None
