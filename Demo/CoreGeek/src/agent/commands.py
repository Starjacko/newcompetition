from typing import Any

from .protocol import (
    CONTROLLABLE_TYPES,
    PIONEER,
    TOWER_TYPES,
    WALL,
    WORKER,
    Turn,
    Pos,
)


def _positions(positions: Pos | list[Pos] | tuple[Pos, ...]) -> list[dict[str, int]]:
    if isinstance(positions, Pos):
        positions = [positions]
    return [position.dump() for position in positions]


def move(pos: Pos) -> dict[str, Any]:
    return {"action": "move", "targetPos": _positions(pos)}


def attack(controller_id: int, targets: Pos | list[Pos]) -> dict[str, Any]:
    return {
        "action": "attack",
        "targetPos": _positions(targets),
        "controllerId": str(controller_id),
    }


def build(pos: Pos, name: str) -> dict[str, Any]:
    return {"action": "build", "targetPos": _positions(pos), "name": name}


def collect(pos: Pos) -> dict[str, Any]:
    return {"action": "collect", "targetPos": _positions(pos)}


def sell(name: str, num: int) -> dict[str, Any]:
    return {"action": "sell", "name": name, "num": max(1, num)}


def buy(name: str, num: int = 1) -> dict[str, Any]:
    return {"action": "buy", "name": name, "num": max(1, num)}


def use(name: str, target: Pos | None = None) -> dict[str, Any]:
    command: dict[str, Any] = {"action": "use", "name": name}
    if target is not None:
        command["targetPos"] = _positions(target)
    return command


def accept_task() -> dict[str, Any]:
    return {"action": "acceptTask"}


def submit_answer(answer: str) -> dict[str, Any]:
    return {"action": "submitAnswer", "taskAnswer": answer}


def summon_treasure(pos: Pos, items: list[str]) -> dict[str, Any]:
    return {
        "action": "summonTreasure",
        "targetPos": _positions(pos),
        "item": list(items),
    }


def validate_commands(commands: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Drop malformed actions before they can become judge-side exceptions."""
    valid_actions = {
        "move", "attack", "sell", "buy", "build", "remove", "acceptTask",
        "submitAnswer", "summonTreasure", "use", "drop", "collect",
    }
    result: dict[int, dict[str, Any]] = {}
    controllers: set[str] = set()
    for role_id, command in commands.items():
        if not isinstance(command, dict):
            continue
        action = command.get("action")
        if action not in valid_actions:
            continue
        if action in {"move", "attack", "build", "remove", "collect", "use", "summonTreasure"}:
            if not command.get("targetPos") and action not in {"use"}:
                continue
        if action == "attack":
            controller_id = command.get("controllerId")
            if not controller_id or controller_id in controllers:
                continue
            controllers.add(controller_id)
        if action in {"sell", "buy", "use", "drop", "build"} and not command.get("name"):
            continue
        result[int(role_id)] = command
    return result


def validate_for_turn(
    turn: Turn,
    commands: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Apply role and phase permissions after generic shape validation."""
    accepted, _rejected = validate_for_turn_detailed(turn, commands)
    return accepted


def validate_for_turn_detailed(
    turn: Turn,
    commands: dict[int, dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    """Return accepted actions plus machine-readable rejection reasons."""
    commands = validate_commands(commands)
    by_id = {unit.unit_id: unit for unit in turn.ours}
    controllers: set[int] = set()
    result: dict[int, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    for role_id, command in commands.items():
        actor = by_id.get(role_id)
        if actor is None or actor.health <= 0:
            rejected.append({"roleId": role_id, "reason": "missing_or_dead_role"})
            continue
        action = command["action"]
        allowed = True
        reason = ""
        if action == "attack":
            try:
                controller_id = int(command["controllerId"])
            except (TypeError, ValueError):
                controller_id = None
            allowed = (
                not turn.is_day
                and actor.kind in TOWER_TYPES
                and controller_id in {
                    unit.unit_id for unit in turn.alive(CONTROLLABLE_TYPES)
                }
                and controller_id not in controllers
            )
            if not allowed:
                reason = "attack_permission_or_duplicate_controller"
            if allowed:
                controllers.add(controller_id)
        elif action in {"build", "remove", "collect"}:
            allowed = turn.is_day and actor.kind == WORKER
            if not allowed:
                reason = "worker_day_only"
        elif action in {"acceptTask", "submitAnswer", "summonTreasure"}:
            allowed = actor.kind == PIONEER
            if not allowed:
                reason = "pioneer_only"
        elif action in {"move", "sell", "buy", "use", "drop"}:
            allowed = actor.kind in (*CONTROLLABLE_TYPES,)
            if not allowed:
                reason = "controllable_role_only"
        if action == "build":
            allowed = allowed and command.get("name") in {
                "wall", "rocket", "railgun", "gatling",
            }
            if not allowed and not reason:
                reason = "unsupported_build_name"
        if action == "remove":
            allowed = allowed and bool(turn.walls())
            if not allowed and not reason:
                reason = "no_wall_to_remove"
        if allowed:
            result[role_id] = command
        else:
            rejected.append({
                "roleId": role_id,
                "action": action,
                "reason": reason or "permission_denied",
            })
    return result, rejected
