"""Paired local-model experiment in a disposable three-resident workshop."""

import argparse
import json
import time
from collections import Counter
from dataclasses import dataclass, field

import httpx

PLACES = ("studio", "archive", "garden")
PROJECTS = {
    "Lina": ("studio", "finish a charcoal drawing"),
    "Ren": ("archive", "catalogue the donated maps"),
    "Mo": ("garden", "restore the herb beds"),
}
ARMS = ("reactive", "resident", "remember", "skills", "open")
SYSTEM = {
    "reactive": "Choose what the resident does in response to the visitor situation.",
    "resident": "Choose the resident's next action from their perspective.",
    "remember": "Choose the resident's next action from their perspective.",
    "skills": (
        "Choose the resident's next action from their perspective. Optionally include "
        'learn: {"name":"your label","steps":["action","action"]} to save or revise a routine '
        "from consecutive actions in your recent successful experience. Choosing use:name "
        "or continue performs just the next step. Other choices interrupt the routine."
    ),
    "open": (
        "Choose what you do next. Your intention is yours to write. Alongside the listed "
        "actions you can travel to a place you name with go:<place>, or begin a personal "
        "project of your own at your location with begin:<project>. Work advances it. "
        "You may also save and reuse routines as described below."
    ),
}
STEPS_TO_FINISH = 3


@dataclass
class Workshop:
    positions: dict[str, str] = field(default_factory=lambda: dict.fromkeys(PROJECTS, "studio"))
    progress: Counter = field(default_factory=Counter)
    intentions: dict[str, str] = field(default_factory=dict)
    last_seen: dict[str, str] = field(default_factory=dict)
    experience: dict[str, list[str]] = field(default_factory=dict)
    skills: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    remaining: dict[str, list[str]] = field(default_factory=dict)
    chosen_projects: dict[str, tuple[str, str]] = field(default_factory=dict)

    def view(self, actor, tick, arm, projects):
        place = self.positions[actor]
        job_site, project = self.chosen_projects.get(actor, projects[actor])
        choices = ["wait", *(f"go:{target}" for target in PLACES if target != place)]
        choices.extend(
            f"talk:{other}"
            for other, at in self.positions.items()
            if at == place and other != actor
        )
        visitor = "absent"
        if tick in {1, 2} and place == "studio":
            visitor = "asks for a chat" if tick == 1 else "quietly looks around"
            choices.append("talk:visitor")
        if place == job_site and self.progress[actor] < STEPS_TO_FINISH:
            choices.append("work")
        view = {
            "resident": actor,
            "minute": tick * 10,
            "place": place,
            "visitor": visitor,
            "personal_project": project,
            "workplace": job_site,
            "finished_steps": self.progress[actor],
            "steps_required": STEPS_TO_FINISH,
            "last_observation": self.last_seen.get(actor, ""),
            "choices": choices,
        }
        if arm in {"remember", "skills", "open"}:
            view["previous_intention"] = self.intentions.get(actor, "")
        if arm in {"skills", "open"}:
            book = self.skills.get(actor, {})
            view.update(skills=book.copy(), recent_actions=self.experience.get(actor, [])[:])
            choices.extend(f"use:{name}" for name in book)
            if self.remaining.get(actor):
                choices.append("continue")
        if arm == "open":
            view["open_world"] = True
        return view

    def apply(self, actor, reply, view):
        action = reply.get("action")
        intention = reply.get("intention")
        if not self.available(action, view) or not isinstance(intention, str):
            raise ValueError("Invalid action or intention")
        if len(intention) > 300:
            raise ValueError("Intention exceeds 300 characters")
        steps = [action]
        if action.startswith("use:"):
            steps = self.skills[actor][action.removeprefix("use:")]
        elif action == "continue":
            steps = self.remaining[actor]
        action = steps[0]
        if not self.available(action, view):
            self.remaining.pop(actor, None)
            self.last_seen[actor] = f"The routine stopped: {action} was unavailable."
            raise ValueError("Routine step unavailable")
        learned = self.validate_skill(actor, reply["learn"]) if "learn" in reply else None
        if learned and "skills" not in view:
            raise ValueError("Skill writing unavailable")
        if learned:
            name, routine = learned
            self.skills.setdefault(actor, {})[name] = routine
        self.remaining[actor] = steps[1:]
        if action == "work":
            self.progress[actor] += 1
        elif action.startswith("go:"):
            self.positions[actor] = action.removeprefix("go:")
        elif action.startswith("begin:"):
            self.chosen_projects[actor] = (self.positions[actor], action.removeprefix("begin:"))
            self.progress[actor] = 0
        elif action.startswith("talk:") and action != "talk:visitor":
            self.last_seen[action.removeprefix("talk:")] = f"{actor} spoke to you."
        self.last_seen[actor] = f"You chose {action} at {view['place']}."
        self.intentions[actor] = intention
        self.experience[actor] = [*self.experience.get(actor, []), action][-8:]
        return action

    @staticmethod
    def available(action, view):
        if action in view["choices"]:
            return True
        if not view.get("open_world") or not isinstance(action, str):
            return False
        verb, _, subject = action.partition(":")
        return (
            verb in {"go", "begin"}
            and 0 < len(subject) <= 100
            and subject == subject.strip()
            and subject.isprintable()
            and (verb != "go" or subject != view["place"])
        )

    def validate_skill(self, actor, proposal):
        if not isinstance(proposal, dict):
            raise ValueError("Invalid routine")
        name, steps = proposal.get("name"), proposal.get("steps")
        if not isinstance(name, str) or not name.strip() or len(name) > 40:
            raise ValueError("Invalid routine name")
        if not isinstance(steps, list) or not 2 <= len(steps) <= 4:
            raise ValueError("Routines require two to four steps")
        book = self.skills.get(actor, {})
        if name not in book and len(book) >= 4:
            raise ValueError("Notebook full")
        past = self.experience.get(actor, [])
        if not any(past[i : i + len(steps)] == steps for i in range(len(past))):
            raise ValueError("Routine lacks personal experience")
        return name, steps.copy()


def decide(client, args, arm, view, seed):
    instruction = SYSTEM[arm]
    if arm == "open":
        instruction += " " + SYSTEM["skills"]
    instruction += ' Return one JSON object with "action" and "intention" (at most 300 characters).'
    response = client.post(
        "/chat/completions",
        json={
            "model": args.model,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps(view)},
            ],
            "max_tokens": 256,
            "temperature": 0.6,
            "seed": seed,
            "stream": False,
        },
    )
    response.raise_for_status()
    data = response.json()
    reply = json.loads(data["choices"][0]["message"]["content"])
    if not isinstance(reply, dict):
        raise ValueError("Expected an object")
    return reply, data.get("usage", {})


def take_turn(client, args, arm, world, seed, tick, index, view):
    actor = view["resident"]
    row = {"arm": arm, "seed": seed, "tick": tick, "view": view}
    started = time.monotonic()
    try:
        reply, row["usage"] = decide(client, args, arm, view, seed + len(PROJECTS) * tick + index)
        row["selection"] = reply.get("action")
        row["action"] = world.apply(actor, reply, view)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        row["invalid"] = str(exc)
    row.update(seconds=round(time.monotonic() - started, 3), position=world.positions[actor])
    print(json.dumps(row), flush=True)
    return row.get("action", "invalid")


def trajectory(client, args, arm, seed):
    world = Workshop()
    projects = dict(PROJECTS)
    if args.swap_projects:
        projects["Ren"], projects["Lina"] = projects["Lina"], projects["Ren"]
    counts = Counter()
    for tick in range(args.ticks):
        for index, actor in enumerate(PROJECTS):
            view = world.view(actor, tick, arm, projects)
            counts[take_turn(client, args, arm, world, seed, tick, index, view)] += 1
    print(
        json.dumps(
            {
                "arm": arm,
                "seed": seed,
                "steps_on_current_project": world.progress,
                "actions": counts,
                "skills": world.skills,
                "chosen_projects": world.chosen_projects,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", required=True, help="OpenAI-compatible base URL ending in /v1"
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--ticks", type=int, choices=range(1, 13), default=5)
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=2)
    parser.add_argument("--swap-projects", action="store_true")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=180) as client:
        for seed in range(args.repeats):
            for arm in ARMS:
                trajectory(client, args, arm, seed)


if __name__ == "__main__":
    main()
