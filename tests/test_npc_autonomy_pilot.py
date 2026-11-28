"""Exercise the complete pilot with a synthetic endpoint, including failed choices."""

import json
from types import SimpleNamespace

import httpx
import pytest

from scripts.npc_autonomy_context import bounded_messages
from scripts.npc_autonomy_pilot import PROJECTS, Workshop, trajectory


def test_workshop_trace_records_committed_work_and_invalid_choices(capsys):
    def endpoint(request):
        assert request.url.path == "/v1/chat/completions"
        view = json.loads(json.loads(request.content)["messages"][1]["content"])
        action = {"Ren": "go:archive", "Mo": "invent"}.get(view["resident"], "work")
        if action == "go:archive" and view["place"] == "archive":
            action = "work"
        content = json.dumps({"action": action, "intention": "Return after tea."})
        if view["resident"] == "Ren":
            content = f"```json\n{content}\n```"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    args = SimpleNamespace(swap_projects=False, turns=12, input_tokens=32000, model="synthetic")
    with httpx.Client(
        base_url="http://pilot/v1", transport=httpx.MockTransport(endpoint)
    ) as client:
        trajectory(client, args, "remember", 0)
    *rows, summary = map(json.loads, capsys.readouterr().out.splitlines())
    assert summary["steps_on_current_project"] == {"Lina": 3, "Ren": 3}
    assert summary["actions"]["invalid"] == 5
    assert rows[3]["view"]["visitor"] == "asks for a chat"
    assert rows[4]["view"]["visitor"] == "absent"
    assert rows[4]["view"]["previous_intention"] == "Return after tea."
    assert rows[5]["view"]["previous_intention"] == ""


def test_open_resident_creates_project_and_reuses_only_experienced_steps():
    world = Workshop()

    def act(action, **extra):
        return world.apply(
            "Lina",
            {"action": action, "intention": "", **extra},
            world.view("Lina", 0, "open", PROJECTS),
        )

    act("go:bell tower")
    act("begin:map the bells")
    routine = {"name": "survey", "steps": ["work", "work"]}
    with pytest.raises(ValueError, match="personal experience"):
        act("work", learn=routine)
    act("work")
    act("work")
    act("wait", learn=routine)
    assert act("use:survey") == "work"
    with pytest.raises(ValueError, match="unavailable"):
        act("continue")
    assert world.progress["Lina"] == 3 and world.positions["Lina"] == "bell tower"
    assert "survey" not in world.view("Ren", 1, "open", PROJECTS)["skills"]


def test_notebook_private_edits_and_bounded_recall():
    world = Workshop()
    for text in ("Remember the bell.", "Maybe a different bell.", ""):
        view = world.view("Lina", 0, "open", PROJECTS)
        world.apply(
            "Lina",
            {"action": "wait", "intention": "", "note": {"title": "Bells", "text": text}},
            view,
        )
        notes = world.view("Lina", 1, "open", PROJECTS)["private_notebook"]
        assert notes == ({"Bells": text} if text else {})
        assert "Bells" not in json.dumps(world.view("Ren", 1, "open", PROJECTS))
    history = [f"{i}: " + "x" * 80 for i in range(700)]
    prompt = bounded_messages("Choose", {"witnessed_events": history}, 32000)[1]["content"]
    kept = json.loads(prompt)["witnessed_events"]
    assert len(prompt.encode()) < 32000 and 0 < len(kept) < len(history)
    assert kept == history[-len(kept) :]
