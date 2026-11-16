"""Expected state conflicts defer automatic work without masking model failures."""

from fastapi import HTTPException


class SimulationConflict(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=409, detail=detail)
