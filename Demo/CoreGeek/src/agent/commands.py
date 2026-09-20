from typing import Any

from .protocol import (
    CONTROLLABLE_TYPES,
    STATION,
    TOWER_TYPES,
    WALL,
    WORKER,
    Turn,
    Pos,
    Unit,
    distance,
)

# 角色值来自接口文档；命令校验不依赖 protocol.py 中的同名别名，
# 避免部署环境加载旧模块时出现 NameError。
PIONEER_ROLE = "pioneer"


TARGET_REQUIRED_ITEMS = {
    "WallFixer",
    "DizzyWeapon",
    "Bomb",
    "WeaponUpgradeVoucher1",
    "WeaponUpgradeVoucher2",
    "WallUpgradeVoucher1",
    "WallUpgradeVoucher2",
    "StationUpgradeVoucher1",
    "StationUpgradeVoucher2",
}
WEAPON_UPGRADE_ITEMS = {"WeaponUpgradeVoucher1", "WeaponUpgradeVoucher2"}
WALL_TARGET_ITEMS = {"WallFixer", "WallUpgradeVoucher1", "WallUpgradeVoucher2"}
STATION_UPGRADE_ITEMS = {"StationUpgradeVoucher1", "StationUpgradeVoucher2"}


def _positions(positions: Pos | list[Pos] | tuple[Pos, ...]) -> list[dict[str, int]]:
    if isinstance(positions, Pos):
        positions = [positions]
    return [position.dump() for position in positions]


def _valid_positions(raw: Any) -> bool:
    return (
        isinstance(raw, list)
        and bool(raw)
        and all(
            isinstance(position, dict)
            and isinstance(position.get("x"), int)
            and not isinstance(position.get("x"), bool)
            and isinstance(position.get("y"), int)
            and not isinstance(position.get("y"), bool)
            for position in raw
        )
    )


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
        try:
            normalized_role_id = int(role_id)
        except (TypeError, ValueError):
            continue
        action = command.get("action")
        if action not in valid_actions:
            continue
        if action in {"move", "attack", "build", "remove", "collect", "use", "summonTreasure"}:
            if action != "use" and not _valid_positions(command.get("targetPos")):
                continue
            if action == "use" and "targetPos" in command and not _valid_positions(command["targetPos"]):
                continue
            if action in {"move", "build", "remove", "collect", "summonTreasure"}:
                if len(command.get("targetPos", [])) != 1:
                    continue
            if action == "use" and "targetPos" in command:
                if len(command["targetPos"]) != 1:
                    continue
        if action == "attack":
            controller_id = command.get("controllerId")
            try:
                normalized_controller_id = int(controller_id)
            except (TypeError, ValueError):
                continue
            if normalized_controller_id in controllers:
                continue
            controllers.add(normalized_controller_id)
            command = dict(command)
            command["controllerId"] = str(normalized_controller_id)
        if action in {"sell", "buy", "use", "drop", "build"} and not command.get("name"):
            continue
        if action == "submitAnswer" and not str(command.get("taskAnswer") or "").strip():
            continue
        if action == "summonTreasure":
            items = command.get("item")
            if (
                not isinstance(items, list)
                or not items
                or not all(isinstance(item, str) and item for item in items)
            ):
                continue
        if action in {"sell", "buy"} and "num" in command:
            if not isinstance(command["num"], int) or isinstance(command["num"], bool):
                continue
            if command["num"] <= 0:
                continue
        result[normalized_role_id] = command
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
    # 先做字段级校验，再做角色权限和昼夜规则校验。
    rejected: list[dict[str, Any]] = []
    for role_id, command in commands.items():
        if (
            isinstance(command, dict)
            and command.get("action") == "attack"
            and not _is_int_like(command.get("controllerId"))
        ):
            try:
                normalized_role_id = int(role_id)
            except (TypeError, ValueError):
                continue
            rejected.append({
                "roleId": normalized_role_id,
                "action": "attack",
                "reason": "invalid_controller_id",
            })
    commands = validate_commands(commands)
    by_id = {unit.unit_id: unit for unit in turn.ours}
    controllers: set[int] = set()
    result: dict[int, dict[str, Any]] = {}
    for role_id, command in commands.items():
        actor = by_id.get(role_id)
        if actor is None or actor.health <= 0:
            rejected.append({"roleId": role_id, "reason": "missing_or_dead_role"})
            continue
        action = command["action"]
        allowed = True
        reason = ""
        if action == "attack":
            # 响应 key 是炮台 ID，controllerId 必须是存活的可控角色 ID。
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
        elif action in {"build", "collect"}:
            allowed = turn.is_day and actor.kind == WORKER
            if not allowed:
                reason = "worker_day_only"
        elif action == "remove":
            allowed = actor.kind == WORKER
            if not allowed:
                reason = "worker_only"
        elif action in {"acceptTask", "submitAnswer", "summonTreasure"}:
            allowed = actor.kind == PIONEER_ROLE
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
        if action in {"build", "remove", "collect"} and allowed:
            target = Pos.load(command["targetPos"][0])
            if max(abs(actor.pos.x - target.x), abs(actor.pos.y - target.y)) > 1:
                allowed = False
                reason = "target_out_of_interaction_range"
        if action == "remove":
            target = Pos.load(command["targetPos"][0])
            allowed = allowed and any(
                wall.pos == target for wall in turn.walls()
            )
            if not allowed and not reason:
                reason = "target_is_not_wall"
        if action == "collect" and allowed:
            target = Pos.load(command["targetPos"][0])
            if target not in turn.mines():
                allowed = False
                reason = "target_is_not_mine"
        if action == "attack" and allowed:
            controller_id = int(command["controllerId"])
            controller = next(
                (
                    unit for unit in turn.alive(CONTROLLABLE_TYPES)
                    if unit.unit_id == controller_id
                ),
                None,
            )
            if controller is None or distance(controller.pos, actor.pos) > 1:
                allowed = False
                reason = "controller_out_of_range"
            else:
                expected = (
                    max(actor.level, 1)
                    if actor.kind in {"gatling", "rocket"}
                    else 1
                )
                if len(command["targetPos"]) != expected:
                    allowed = False
                    reason = "invalid_target_count"
                elif any(
                    distance(actor.pos, Pos.load(target)) > actor.range_of_attack()
                    for target in command["targetPos"]
                ):
                    allowed = False
                    reason = "target_out_of_attack_range"
                elif actor.kind == "gatling" and not _same_gatling_cone(actor, command):
                    allowed = False
                    reason = "gatling_targets_not_same_cone"
        if action == "use" and allowed:
            name = command["name"]
            has_target = "targetPos" in command
            if name in TARGET_REQUIRED_ITEMS and not has_target:
                allowed = False
                reason = "target_required_for_item"
            elif has_target:
                target = Pos.load(command["targetPos"][0])
                allowed, reason = _validate_use_target(turn, actor, name, target)
        if action == "summonTreasure" and allowed:
            if distance(actor.pos, Pos.load(command["targetPos"][0])) > 1:
                allowed = False
                reason = "target_out_of_interaction_range"
        if allowed:
            result[role_id] = command
        else:
            rejected.append({
                "roleId": role_id,
                "action": action,
                "reason": reason or "permission_denied",
            })
    return result, rejected


def _is_int_like(value: Any) -> bool:
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    return value is not None and not isinstance(value, bool)


def _same_gatling_cone(weapon: Unit, command: dict[str, Any]) -> bool:
    """加特林多目标必须处于同一 90 度锥形内，这是任务书明确非法条件。"""
    targets = [Pos.load(target) for target in command["targetPos"]]
    for index, first in enumerate(targets):
        first_dx = first.x - weapon.pos.x
        first_dy = first.y - weapon.pos.y
        for second in targets[index + 1:]:
            second_dx = second.x - weapon.pos.x
            second_dy = second.y - weapon.pos.y
            if first_dx * second_dx + first_dy * second_dy < 0:
                return False
    return True


def _validate_use_target(
    turn: Turn,
    actor: Unit,
    name: str,
    target: Pos,
) -> tuple[bool, str]:
    if name in WEAPON_UPGRADE_ITEMS:
        return _target_building(turn, target, TOWER_TYPES, actor)
    if name in WALL_TARGET_ITEMS:
        return _target_building(turn, target, (WALL,), actor)
    if name in STATION_UPGRADE_ITEMS:
        return _target_building(turn, target, (STATION,), actor)
    # Medicine 和机器人召唤令没有目标要求；如果传了合法 targetPos，也不把它升级为接口错误。
    return True, ""


def _target_building(
    turn: Turn,
    target: Pos,
    kinds: tuple[str, ...],
    actor: Unit,
) -> tuple[bool, str]:
    building = next(
        (unit for unit in turn.ours if unit.kind in kinds and unit.pos == target),
        None,
    )
    if building is None:
        return False, "target_building_type_mismatch"
    if distance(actor.pos, target) > 1:
        return False, "target_out_of_interaction_range"
    return True, ""
