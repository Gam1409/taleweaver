"""Typed personal-notebook requests; the host supplies identity and storage scope."""

from typing import Annotated, Literal

from pydantic import AfterValidator, ConfigDict, Field, StrictInt, StrictStr, model_validator

from backend.engine.chpm.schema import Contract


def _unicode(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Notebook paths must be valid Unicode.") from exc
    return value


class NotebookContract(Contract):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


Pointer = Annotated[StrictStr, Field(max_length=8192), AfterValidator(_unicode)]
Revision = Annotated[StrictInt, Field(ge=0)]
ValueJson = Annotated[str, Field(min_length=1, max_length=8192)]


class NotebookInfo(NotebookContract):
    tool: Literal["notebook_info"]


class NotebookRead(NotebookContract):
    tool: Literal["notebook_read"]
    path: Pointer = ""
    offset: Annotated[StrictInt, Field(ge=0)] = 0
    limit: Annotated[StrictInt, Field(ge=256, le=1400)] = 1400


class NotebookWrite(NotebookContract):
    tool: Literal["notebook_write"]
    path: Pointer = ""
    expected_revision: Revision
    value_json: ValueJson


class NotebookOperation(NotebookContract):
    op: Literal["add", "replace", "remove", "test"]
    path: Pointer
    value_json: ValueJson | None = None

    @model_validator(mode="after")
    def value_matches_operation(self) -> "NotebookOperation":
        if (self.op == "remove") != (self.value_json is None):
            raise ValueError("Only remove omits value_json; other operations need exact JSON.")
        return self


class NotebookEdit(NotebookContract):
    tool: Literal["notebook_edit"]
    expected_revision: Revision
    operations: list[NotebookOperation] = Field(min_length=1, max_length=16)


class NotebookDelete(NotebookContract):
    tool: Literal["notebook_delete"]
    path: Pointer = ""
    expected_revision: Revision


NotebookRequest = NotebookInfo | NotebookRead | NotebookWrite | NotebookEdit | NotebookDelete
