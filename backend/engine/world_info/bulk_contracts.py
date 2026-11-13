"""Explicit, reviewable changes to a server-selected knowledge collection."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from backend.engine.world_info import limits
from backend.engine.world_info.schemas import EntryFilters
from backend.engine.world_info.types import Contract, validate_text

BulkAction = Literal["set_group", "add_tags", "remove_tags", "publish"]
Tag = Annotated[str, Field(min_length=1, max_length=limits.MAX_TAG_CHARACTERS)]


class BulkRequest(Contract):
    action: BulkAction
    filters: EntryFilters
    group_name: str | None = Field(default=None, max_length=limits.MAX_GROUP_CHARACTERS)
    tags: list[Tag] = Field(default_factory=list, max_length=limits.MAX_TAGS)

    @model_validator(mode="after")
    def action_parameters(self) -> "BulkRequest":
        if self.action == "set_group" and (self.group_name is None or self.tags):
            raise ValueError("Choose a group name for this change.")
        if self.action != "set_group" and self.group_name is not None:
            raise ValueError("Group names belong to the group action.")
        if self.group_name is not None and (
            self.group_name != self.group_name.strip()
            or "\n" in self.group_name
            or "\r" in self.group_name
        ):
            raise ValueError("Group names must be a single trimmed line.")
        if self.action in {"add_tags", "remove_tags"} and not self.tags:
            raise ValueError("Choose tags for this change.")
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("Tags must be distinct.")
        for tag in self.tags:
            validate_text(tag)
            if not tag.strip():
                raise ValueError("Tags cannot be empty.")
        if self.action == "publish" and (not self.filters.source_revision_id or self.tags):
            raise ValueError("Publication requires one source revision.")
        return self


class BulkApply(BulkRequest):
    selection_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
