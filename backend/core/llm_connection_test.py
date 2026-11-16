"""One structured connection probe shared by local and cloud providers."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class ConnectionTestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str


async def test_connection(router: Any, model: str) -> str:
    """Test the technical router path; one probe does not certify every task schema."""
    result = await router.aexecute_complex_task(
        system_prompt="You are a helpful RPG assistant.",
        user_prompt='Return a JSON object with a message saying "TaleWeaver connection test successful!".',
        response_model=ConnectionTestResult,
        model=model,
    )
    return str(result.message)
