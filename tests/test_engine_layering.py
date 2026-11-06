"""Domain code must not import transport-route implementations, even lazily."""

import ast
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_engine_does_not_depend_on_api_routes():
    violations = []
    for path in (ROOT / "backend/engine").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("backend.api"):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.module}")
    assert not violations, "Route imports invert the engine boundary:\n" + "\n".join(violations)


def test_legacy_facades_preserve_module_and_class_identity():
    for old, new, symbol in (
        ("gameplay_logic", "manager", "GameTurnManager"),
        ("logic", "world", "AdventureLogic"),
        ("adventure_snapshot", "snapshot", "AdventureSnapshot"),
        ("agent_logic", "agent_logic", "AgentService"),
    ):
        facade = importlib.import_module("backend.api.routes.adventures." + old)
        implementation = importlib.import_module("backend.engine.gameplay." + new)
        assert facade is implementation
        assert getattr(facade, symbol) is getattr(implementation, symbol)
