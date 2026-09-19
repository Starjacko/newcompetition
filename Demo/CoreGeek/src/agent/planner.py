from .combat import hostile_robots, plan as plan_combat
from .commands import validate_for_turn_detailed
from .config import DEFAULT_CONFIG, StrategyConfig
from .layout import attack_face, base_corner
from .logging_utils import event, get_logger
from .memory import PersistentMemory
from .pioneer import PioneerDecision, plan as plan_pioneer
from .protocol import Turn, distance
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
        if workers:
            worker1 = min(workers, key=lambda role: role.unit_id)
            worker2 = max(workers, key=lambda role: role.unit_id)
            preferred[worker1.unit_id] = "rocket"
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
        elif workers and role.unit_id == min(worker.unit_id for worker in workers):
            kind = "rocket"
        elif workers and role.unit_id == max(worker.unit_id for worker in workers):
            kind = "gatling"
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
