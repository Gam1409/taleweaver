"""Compatibility module for the shared unlock service."""

import importlib
import sys

sys.modules[__name__] = importlib.import_module("backend.engine.gameplay.unlock_service")
