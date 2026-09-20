from .combat import hostile_robots, plan as plan_combat
from .commands import validate_for_turn_detailed
from .config import DEFAULT_CONFIG, StrategyConfig
from .layout import attack_face, base_corner
from .logging_utils import event, get_logger
from .memory import PersistentMemory
from .pioneer import PioneerDecision, plan as plan_pioneer
from .protocol import Pos, Turn, distance, worker_slot
from .trace import command_snapshot, role_snapshot, turn_snapshot
from .workers import plan as plan_workers
from .grid import next_step_near

LOGGER = get_logger()


class Planner:
    def __init__(self, memory: PersistentMemory, config: StrategyConfig = DEFAULT_CONFIG) -> None:
        self.memory = memory
        self.config = config

    def decide(self, payload: dict) -> dict:
        turn = Turn.load(payload)
        self.memory.update_context(turn)
        self.memory.base_corner = base_corner(turn)
        self.memory.attack_face = attack_face(turn)

        # 防守优先级高于一切运营动作；白天临近夜晚时也必须先回防。
        if not turn.is_day and hostile_robots(turn):
            mode = "night_defence"
            commands = plan_combat(turn)
            prompt = ""
            execute_cmd = ""
        elif turn.is_day and self._must_return(turn):
            mode = "return_to_defence"
            commands = self._return_to_defence(turn)
            prompt = ""
            execute_cmd = ""
        elif self._has_repeated_failure(turn):
            mode = "failure_recovery"
            commands = self._recovery_commands(turn)
            prompt = ""
            execute_cmd = ""
        else:
            mode = "day_operation" if turn.is_day else "night_operation"
            commands, prompt, execute_cmd = self._operate(turn)

        if turn.phase_task and mode != "day_operation" and mode != "night_operation":
            prompt, execute_cmd = self._keep_active_pioneer_task(
                turn, commands, prompt, execute_cmd,
            )

        commands = self._dedupe_move_targets(turn, commands)
        raw_commands = commands
        commands, rejected = validate_for_turn_detailed(turn, commands)
        self.memory.record(commands)
        event(
            LOGGER,
            20,
            "decision",
            **turn_snapshot(turn),
            mode=mode,
            baseCorner=self.memory.base_corner,
            attackFace=self.memory.attack_face,
            roles=role_snapshot(turn),
            worker1Phase=self.memory.worker1_phase,
            worker2Phase=self.memory.worker2_phase,
            pioneerPhase=self.memory.pioneer_phase,
            pioneerAgentPhase=self.memory.pioneer_agent_phase,
            completedTasks=self.memory.completed_tasks,
            actionFailures=self.memory.action_failures,
            lastFailureReason=self.memory.last_failure_reason,
            sopTypes=sorted(self.memory.sop_library),
            rawCommandCount=len(raw_commands),
            commandCount=len(commands),
            commands=command_snapshot(commands),
            rejectedCommands=rejected,
            promptIssued=bool(prompt),
            executeIssued=bool(execute_cmd),
            promptLength=len(prompt),
            executeLength=len(execute_cmd),
        )
        return {
            "roleCommandMap": {str(role_id): command for role_id, command in commands.items()},
            "prompt": prompt,
            "executeCmd": execute_cmd,
        }

    def _has_repeated_failure(self, turn: Turn) -> bool:
        # 只处理最近连续失败，避免一次历史失败永久打断正常流水线。
        return any(
            self.memory.failed_repeatedly(role.unit_id, turn.round_no)
            for role in turn.controllable()
        )

    def _recovery_commands(self, turn: Turn) -> dict[int, dict]:
        commands: dict[int, dict] = {}
        weapons = {weapon.kind: weapon for weapon in turn.weapons()}
        station = turn.station()
        preferred = {"pioneer": "railgun"}
        workers = turn.workers()
        worker1 = next(
            (role for role in workers if worker_slot(role.unit_id) == 1),
            None,
        )
        worker2 = next(
            (role for role in workers if worker_slot(role.unit_id) == 2),
            None,
        )
        if not workers or not any(worker_slot(role.unit_id) in {1, 2} for role in workers):
            worker1 = min(workers, key=lambda role: role.unit_id, default=None)
            worker2 = max(workers, key=lambda role: role.unit_id, default=None)
        if worker1 is not None:
            preferred[worker1.unit_id] = "rocket"
        if worker2 is not None:
            preferred[worker2.unit_id] = "gatling"
        for role in turn.controllable():
            if not self.memory.failed_repeatedly(role.unit_id, turn.round_no):
                continue
            target = weapons.get(preferred.get(role.unit_id, preferred.get(role.kind, "")))
            if target is None:
                target = station
            if target is None:
                continue
            step = next_step_near(turn, role, target.pos)
            if step is not None:
                commands[role.unit_id] = {
                    "action": "move",
                    "targetPos": [step.dump()],
                }
        return commands

    def _must_return(self, turn: Turn) -> bool:
        # 用“到固定武器的距离 + 安全余量”估计是否来得及在夜晚前回防。
        controllers = turn.controllable()
        if not controllers:
            return False
        rounds_until_night = 70 - ((turn.round_no - 1) % 130)
        weapons = {weapon.kind: weapon for weapon in turn.weapons()}
        if not weapons:
            station = turn.station()
            return station is not None and any(
                rounds_until_night <= distance(role.pos, station.pos)
                + self.config.return_safety_margin
                for role in controllers
            )
        return any(
            rounds_until_night <= distance(role.pos, target.pos)
            + self.config.return_safety_margin
            for role in controllers
            for target in (
                self._preferred_weapon(turn, role, weapons)
                or turn.station(),
            )
            if target is not None
        )

    def _return_to_defence(self, turn: Turn) -> dict[int, dict]:
        # 回防阶段每个角色只发移动命令，暂停采矿、建造、任务和购买。
        commands: dict[int, dict] = {}
        controllers = turn.controllable()
        weapons = {weapon.kind: weapon for weapon in turn.weapons()}
        station = turn.station()
        for role in controllers:
            target = self._preferred_weapon(turn, role, weapons) or station
            if target is None:
                continue
            step = next_step_near(turn, role, target.pos)
            if step is not None:
                commands[role.unit_id] = {
                    "action": "move",
                    "targetPos": [step.dump()],
                }
        return commands

    def _preferred_weapon(
        self,
        turn: Turn,
        role,
        weapons: dict[str, object],
    ):
        workers = turn.workers()
        if role.kind == "pioneer":
            kind = "railgun"
        elif worker_slot(role.unit_id) == 1:
            kind = "rocket"
        elif worker_slot(role.unit_id) == 2:
            kind = "gatling"
        elif workers and not any(worker_slot(worker.unit_id) in {1, 2} for worker in workers):
            kind = (
                "rocket"
                if role.unit_id == min(worker.unit_id for worker in workers)
                else "gatling"
            )
        else:
            kind = ""
        return weapons.get(kind)

    def _operate(self, turn: Turn) -> tuple[dict[int, dict], str, str]:
        commands = plan_workers(turn, self.memory, self.config)
        prompt = ""
        execute_cmd = ""
        pioneers = turn.alive(("pioneer",))
        if pioneers:
            decision: PioneerDecision = plan_pioneer(
                turn, pioneers[0], self.memory, self.config,
            )
            if decision.command is not None:
                commands[pioneers[0].unit_id] = decision.command
            prompt = decision.prompt
            execute_cmd = decision.execute_cmd
        return commands, prompt, execute_cmd

    def _keep_active_pioneer_task(
        self,
        turn: Turn,
        commands: dict[int, dict],
        prompt: str,
        execute_cmd: str,
    ) -> tuple[str, str]:
        pioneers = turn.alive(("pioneer",))
        if not pioneers:
            return prompt, execute_cmd
        pioneer = pioneers[0]
        decision: PioneerDecision = plan_pioneer(
            turn, pioneer, self.memory, self.config,
        )
        if decision.command is not None:
            commands[pioneer.unit_id] = decision.command
        elif decision.prompt or decision.execute_cmd:
            # 自进化任务期间离开任务点一格会结束任务；只有 prompt/executeCmd 时原地等待。
            commands.pop(pioneer.unit_id, None)
        return decision.prompt or prompt, decision.execute_cmd or execute_cmd

    def _dedupe_move_targets(
        self,
        turn: Turn,
        commands: dict[int, dict],
    ) -> dict[int, dict]:
        winners: dict[Pos, int] = {}
        result: dict[int, dict] = {}
        for role_id, command in sorted(
            commands.items(),
            key=lambda item: self._move_priority(turn, item[0]),
        ):
            if command.get("action") != "move":
                result[role_id] = command
                continue
            targets = command.get("targetPos") or []
            if len(targets) != 1:
                result[role_id] = command
                continue
            try:
                target = Pos.load(targets[0])
            except (KeyError, TypeError, ValueError):
                result[role_id] = command
                continue
            if target in winners:
                continue
            winners[target] = role_id
            result[role_id] = command
        return result

    def _move_priority(self, turn: Turn, role_id: int) -> tuple[int, int]:
        role = next((unit for unit in turn.ours if unit.unit_id == role_id), None)
        if role is not None and role.kind == "pioneer" and turn.phase_task:
            return (0, role_id)
        if worker_slot(role_id) == 1:
            return (1, role_id)
        if worker_slot(role_id) == 2:
            return (2, role_id)
        return (3, role_id)
