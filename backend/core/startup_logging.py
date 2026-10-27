"""Configure console logging before importing route and engine modules."""

import logging

from backend.core.config import settings

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(levelname)s:     %(name)s - %(message)s",
)
