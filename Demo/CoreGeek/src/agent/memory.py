import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from .protocol import Pos, Turn


@dataclass
class PersistentMemory:
    """Small cross-request memory; the current request remains the source of truth."""

    team_type: str | None = None
    team_id: str | None = None
    base_corner: str | None = None
    attack_face: str | None = None
    worker1_phase: str = "build_weapons"
    worker1_wall_stage: str | None = None
    worker1_batch_goal: int | None = None
    worker1_building_batch: bool = False
    worker2_phase: str = "mine"
    worker2_mine: Pos | None = None
    worker2_mine_collects: int = 0
    pioneer_phase: str = "find_task"
    completed_tasks: int = 0
    task_started_round: int | None = None
    task_position: Pos | None = None
    task_type: str | None = None
    task_was_active: bool = False
    pioneer_agent_phase: str = "explore"
    last_round: int = 0
    last_day: int = 0
    last_plans: dict[int, dict] = field(default_factory=dict)
    action_failures: dict[int, int] = field(default_factory=dict)
    last_failure_reason: dict[int, str] = field(default_factory=dict)
    sop_library: dict[str, dict[str, Any]] = field(default_factory=dict)
    sop_path: str | None = None

    def update_context(self, turn: Turn) -> None:
        if (
            self.last_round
            and turn.round_no < self.last_round
        ) or (
            self.team_id is not None
            and turn.team_id
            and turn.team_id != self.team_id
        ):
            self.reset_runtime()
        self.team_type = turn.team_type or self.team_type
        self.team_id = turn.team_id or self.team_id
        for role_id, success in turn.last_action_results.items():
            if success:
                previous = self.last_plans.get(role_id) or {}
                if previous.get("action") == "collect":
                    target = _plan_target(previous)
                    if target is not None and target == self.worker2_mine:
                        self.worker2_mine_collects += 1
                self.action_failures.pop(role_id, None)
                self.last_failure_reason.pop(role_id, None)
                continue
            self.action_failures[role_id] = self.action_failures.get(role_id, 0) + 1
            self.last_failure_reason[role_id] = _error_for_role(turn, role_id)
        task_is_active = bool(turn.phase_task)
        if self.task_was_active and not task_is_active:
            if not any(error.code in {1, 4} for error in turn.errors):
                self.completed_tasks += 1
            self.task_position = None
            self.task_type = None
            self.task_started_round = None
            self.pioneer_agent_phase = "explore"
        self.task_was_active = task_is_active
        self.last_round = turn.round_no
        self.last_day = (turn.round_no - 1) // 130 + 1

    def reset_runtime(self) -> None:
        """Reset one match's live state while retaining reusable SOP knowledge."""
        self.worker1_phase = "build_weapons"
        self.worker1_wall_stage = None
        self.worker1_batch_goal = None
        self.worker1_building_batch = False
        self.worker2_phase = "mine"
        self.worker2_mine = None
        self.worker2_mine_collects = 0
        self.pioneer_phase = "find_task"
        self.completed_tasks = 0
        self.task_started_round = None
        self.task_position = None
        self.task_type = None
        self.task_was_active = False
        self.pioneer_agent_phase = "explore"
        self.action_failures.clear()
        self.last_failure_reason.clear()
        self.last_plans.clear()

    def record(self, commands: dict[int, dict]) -> None:
        self.last_plans = dict(commands)

    def failed_repeatedly(self, role_id: int, threshold: int = 2) -> bool:
        return self.action_failures.get(role_id, 0) >= threshold

    def remember_sop(
        self,
        task_type: str,
        *,
        prompt: str = "",
        execute_cmd: str = "",
        output: str = "",
    ) -> None:
        if not task_type:
            return
        record = self.sop_library.setdefault(
            task_type,
            {"attempts": 0, "commands": [], "outputs": [], "answerHints": []},
        )
        record["attempts"] += 1
        if execute_cmd and execute_cmd not in record["commands"]:
            record["commands"].append(execute_cmd[-2000:])
        if output:
            summary = output[-2000:]
            if summary not in record["outputs"]:
                record["outputs"].append(summary)
        if prompt and len(record["answerHints"]) < 3:
            record["answerHints"].append(prompt[-1000:])
        self.save_sop()

    def load_sop(self) -> None:
        if not self.sop_path:
            return
        path = Path(self.sop_path)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            self.sop_library = {
                str(key): value
                for key, value in data.items()
                if isinstance(value, dict)
            }

    def save_sop(self) -> None:
        if not self.sop_path:
            return
        path = Path(self.sop_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(self.sop_library, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except OSError:
            return


def _error_for_role(turn: Turn, role_id: int) -> str:
    for error in turn.errors:
        if error.description:
            return error.description[:200]
    result = turn.last_action_results.get(role_id)
    return "action_failed" if result is False else ""


def _plan_target(command: dict[str, Any]) -> Pos | None:
    targets = command.get("targetPos") or []
    if not targets:
        return None
    try:
        return Pos.load(targets[0])
    except (KeyError, TypeError, ValueError):
        return None


_MEMORY = PersistentMemory(
    sop_path=os.getenv("AGENT_SOP_FILE"),
)
_MEMORY.load_sop()


def get_memory() -> PersistentMemory:
    return _MEMORY
