import json
import logging
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent / "generation_sayings.json"


def _load_sayings() -> list[str]:
    if _DATA_PATH.is_file():
        try:
            with open(_DATA_PATH, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [str(s) for s in data]
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Could not load generation sayings (%s).", type(error).__name__
            )
    return []


class GenerationSayings:
    SAYINGS: list[str] = _load_sayings()
