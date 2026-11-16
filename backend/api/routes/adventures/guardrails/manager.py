"""Compatibility module; implementation lives in the engine layer."""

import importlib
import sys

sys.modules[__name__] = importlib.import_module("backend.engine.gameplay.guardrails.manager")
