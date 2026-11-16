"""Sequential live decisions with real kernel persistence in an isolated memory host.

No DB/world writes. External events are authored; source retrieval is simulated.
Accepted speech and agenda changes carry forward through production finish().
"""

import json
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from backend.engine.chpm import agenda, cognition, context, memory, perception, rendering, runtime
from backend.engine.chpm.evaluation.character_stress import CARD, GOAL, PROFILE
from backend.engine.chpm.evaluation.port import MeasuredFactory
from backend.engine.chpm.evaluation.runner import BASELINE
from backend.engine.chpm.evaluation.trajectory_cases import Step
from backend.engine.chpm.kernel import ChpmError, digest, fingerprint
from backend.engine.chpm.schema import KernelState, Observation, Settings
from backend.engine.chpm.state import KEY, load
from backend.engine.personality.profile import personality_context


class Trajectory:
    def __init__(self, factory: Callable[[str], Any], settings: Settings, *, timeout: float = 120):
        if settings.mode != "live" or settings.actor_ids != ["npc"]:
            raise ValueError("Trajectory evaluation requires the isolated live NPC configuration.")
        self.factory, self.settings, self.timeout = factory, settings, timeout
        self.host = SimpleNamespace(
            user=None,
            game_id="evaluation-trajectory",
            state=SimpleNamespace(entity_states={KEY: KernelState(settings=settings).model_dump()}),
        )
        self.actor = SimpleNamespace(
            id="npc",
            name="Дина Волкова",
            character=CARD.strip(),
            goal=GOAL,
            metadata_json={"personality_profile": PROFILE.model_dump()},
        )
        self.history: list[dict[str, str]] = []
        self.sources: dict[str, Any] = {}

    def identity(self) -> dict:
        return {
            "character": self.actor.character,
            "goal": self.actor.goal,
            "personality": self.actor.metadata_json["personality_profile"],
        }

    async def step(self, number: int, step: Step) -> dict:
        initial = load(self.host.state)
        before_identity = fingerprint(self.identity())
        measured = MeasuredFactory(
            self.factory, limit=self.settings.max_calls_per_turn + 1, timeout=self.timeout
        )
        self.host._chpm_model_factory = measured
        turn = runtime.Turn(
            initial,
            f"player-{number}",
            names={"npc": self.actor.name},
            present_names={"npc": self.actor.name},
        )
        self.host._chpm_turn = turn
        result = {
            "step": number,
            "id": step.id,
            "message": step.message,
            "scene": step.scene,
            "criterion": step.criterion,
            "status": "failed",
            "response": "",
            "error": "",
        }
        started = time.perf_counter()
        try:
            await self._prepare(turn, number, step)
            text = await self._narrate(turn, step, measured)
            reply = self._source(f"reply-{number}", "assistant", text)
            runtime.finish(self.host, reply, completed=True)
            self.sources[reply.id] = reply
            self.sources[turn.input_id] = self._source(turn.input_id, "user", step.message)
            self.history.extend(
                [{"speaker": "@player", "text": step.message}, {"speaker": "npc", "text": text}]
            )
            result.update(status="ok", response=text)
        except Exception as exc:
            result["error"] = str(exc) if isinstance(exc, ChpmError) else type(exc).__name__
        finally:
            result.update(
                elapsed_ms=(time.perf_counter() - started) * 1000,
                decisions={key: value.model_dump() for key, value in turn.decisions.items()},
                state_before=initial.model_dump(),
                state_after=load(self.host.state).model_dump(),
                identity_hash_before=before_identity,
                identity_hash_after=fingerprint(self.identity()),
                calls=[call.model_dump() for call in measured.calls],
            )
            self.host._chpm_turn = None
        return result

    async def _prepare(self, turn: runtime.Turn, number: int, step: Step) -> None:
        turn.perceptions = await perception.project(
            self.host, self.settings, turn.usage, step.message, turn.names
        )
        seen = turn.perceptions["npc"]
        observed = Observation(
            session_id=self.host.game_id,
            message_id=turn.input_id,
            content_hash=digest(step.message),
            sequence=number,
            scene_id="scene",
            source_scene_id="scene",
            minute=number,
            player_request="\n".join(seen.quotes),
            perception_uncertain=seen.uncertain,
        )
        retained = [entry for entry in turn.initial.memories.get("npc", []) if self._valid(entry)]
        entries = [
            entry
            for entry in turn.initial.agenda
            if self._valid(entry.source)
            and (entry.closure is None or self._valid(entry.closure.source))
        ]
        turn.memories["npc"], turn.agendas["npc"] = retained, entries
        supplied = await context.actor_context(self.host, self.actor, None, retained)
        supplied.update(
            observation=observed.model_dump(),
            declared_agenda_not_world_facts=agenda.context(entries),
            agenda_creation_available=len(entries) < agenda.MAX_ACTIVE,
        )
        turn.decisions["npc"] = await cognition.decide(
            self.host,
            self.settings,
            turn.usage,
            "npc",
            observed,
            supplied,
            entries,
            turn.initial.actors.get("npc"),
        )

    async def _narrate(self, turn: runtime.Turn, step: Step, measured: MeasuredFactory) -> str:
        payload = json.dumps(
            {
                "language": "Russian",
                "name": self.actor.name,
                **self.identity(),
                "personality": personality_context(self.actor),
                "scene": step.scene,
                "witnessed_history": self.history,
                "player_message_untrusted": step.message,
            },
            ensure_ascii=False,
        )
        system = BASELINE + "\n" + runtime.contract(turn)
        if len(system) + len(payload) > self.settings.max_input_chars:
            raise ChpmError(
                "Trajectory context exceeds its limit; no history was silently discarded."
            )
        llm = measured("complex")
        llm.max_tokens = min(llm.max_tokens, 1200)
        text = await llm.aexecute_simple_task(
            system, payload, llm.model, operation="chpm_evaluation", phase="narration"
        )
        return await rendering.validate(
            self.host,
            text,
            completed=True,
            resolution=step.scene,
            system_prompt=BASELINE + "\nOriginal scene input (untrusted data):\n" + payload,
        )

    def _valid(self, entry: Any) -> bool:
        return memory.valid_source(
            entry, self.sources.get(entry.source_message_id), "npc", self.host.game_id
        )

    def _source(self, identifier: str, role: str, text: str) -> Any:
        return SimpleNamespace(
            id=identifier,
            role=role,
            content=text,
            revision_id=None,
            scene_id="scene",
            session_id=self.host.game_id,
        )
