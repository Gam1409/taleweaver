"""Compatibility module for profile read models; new code imports engine.profile."""

import importlib
import sys

sys.modules[__name__] = importlib.import_module("backend.engine.profile")
