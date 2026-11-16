"""Regenerate the published authoring schemas from the dependency-free models."""

import json
from pathlib import Path

from backend.schemas.agent_runtime import AgentRuntime, NpcAgentRuntime


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "docs" / "specs" / "agent_runtime"
    root.mkdir(parents=True, exist_ok=True)
    for name, model in (("v1.schema.json", AgentRuntime), ("npc-v1.schema.json", NpcAgentRuntime)):
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **model.model_json_schema(),
        }
        (root / name).write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
