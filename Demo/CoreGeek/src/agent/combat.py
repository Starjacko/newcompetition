from .commands import attack, move
from .grid import next_step_near
from .protocol import Robot, Turn, Unit, distance, worker_slot


ROLE_WEAPON_PREFERENCE = {
    "worker1": "rocket",
    "pioneer": "railgun",
    "worker2": "gatling",
}


def hostile_robots(turn: Turn) -> tuple[Robot, ...]:
    """Only robots whose targetTeam is ours trigger full-team defence."""
    # 老版本请求可能没有 targetTeam，缺失时保守视为潜在威胁。
    return tuple(
        robot for robot in turn.robots
        if robot.target_team == turn.team_type or robot.target_team is None
    )


def plan(turn: Turn) -> dict[int, dict]:
    threats = hostile_robots(turn)
    if not threats:
        return {}
    # 角色和武器按固定职责绑定；fallback 只在目标武器暂时不存在时使用。
    weapons = {weapon.kind: weapon for weapon in turn.weapons()}
    controllers = _controllers_by_preference(turn)
    commands: dict[int, dict] = {}
    used_weapons: set[int] = set()
    for controller, preferred_kind in controllers:
        weapon = weapons.get(preferred_kind)
        if weapon is not None and weapon.unit_id in used_weapons:
            weapon = None
        if weapon is None:
            weapon = _nearest_weapon(
                turn,
                controller,
                tuple(
                    candidate for candidate in weapons.values()
                    if candidate.unit_id not in used_weapons
                ),
            )
        if weapon is not None:
            used_weapons.add(weapon.unit_id)
            target = weapon.pos
        else:
            # 武器尚未建满时也不能让角色留在矿区；先回基地等待可用炮台。
            station = turn.station()
            if station is None:
                continue
            target = station.pos
        if distance(controller.pos, target) <= 1 and weapon is not None:
            targets = _targets_for(weapon, threats)
            if targets and weapon.cooldown == 0:
                commands[weapon.unit_id] = attack(controller.unit_id, targets)
        else:
            step = next_step_near(turn, controller, target)
            if step is not None:
                commands[controller.unit_id] = move(step)
    return commands


def _controllers_by_preference(
    turn: Turn,
) -> tuple[tuple[Unit, str], ...]:
    workers = turn.workers()
    worker1_id = next(
        (worker.unit_id for worker in workers if worker_slot(worker.unit_id) == 1),
        None,
    )
    worker2_id = next(
        (worker.unit_id for worker in workers if worker_slot(worker.unit_id) == 2),
        None,
    )
    has_documented_slots = any(
        worker_slot(worker.unit_id) in {1, 2} for worker in workers
    )
    if worker1_id is None and workers and not has_documented_slots:
        worker1_id = min(worker.unit_id for worker in workers)
    if worker2_id is None and workers and not has_documented_slots:
        worker2_id = max(worker.unit_id for worker in workers)
    result: list[tuple[Unit, str]] = []
    for role in turn.controllable():
        if role.kind == "pioneer":
            preferred = ROLE_WEAPON_PREFERENCE["pioneer"]
        elif role.unit_id == worker1_id:
            preferred = ROLE_WEAPON_PREFERENCE["worker1"]
        elif role.unit_id == worker2_id:
            preferred = ROLE_WEAPON_PREFERENCE["worker2"]
        else:
            continue
        result.append((role, preferred))
    return tuple(result)


def _nearest_weapon(
    turn: Turn,
    controller: Unit,
    weapons: tuple[Unit, ...] | list[Unit],
) -> Unit | None:
    return min(
        weapons,
        key=lambda weapon: (distance(controller.pos, weapon.pos), weapon.unit_id),
        default=None,
    )


def _targets_for(weapon: Unit, threats: tuple[Robot, ...]) -> list:
    reachable = [
        robot for robot in threats
        if distance(weapon.pos, robot.pos) <= weapon.range_of_attack()
    ]
    if not reachable:
        return []
    ranked = sorted(
        reachable,
        key=lambda robot: (
            0 if robot.kind == "bossRobot" else 1,
            robot.health,
            distance(weapon.pos, robot.pos),
            robot.robot_id,
        ),
    )
    # 炮台等级决定最多可提交的目标数；低等级武器仍只提交一个目标。
    count = max(weapon.level, 1)
    if weapon.kind not in {"gatling", "rocket"}:
        return [ranked[0].pos]
    primary = ranked[0]
    if weapon.kind == "rocket":
        selected = ranked[:count]
        while len(selected) < count:
            selected.append(primary)
        return [robot.pos for robot in selected]

    selected = [primary]
    for robot in ranked[1:]:
        if len(selected) >= count:
            break
        if all(_same_cone(weapon, existing, robot) for existing in selected):
            selected.append(robot)
    # 接口要求加特林/火箭目标数组长度等于武器等级。
    # 目标不足时重复最优落点；火箭规则允许重复落点叠加伤害。
    while len(selected) < count:
        selected.append(primary)
    return [robot.pos for robot in selected[:count]]


def _same_cone(weapon: Unit, first: Robot, second: Robot) -> bool:
    # 点积非负表示夹角不超过 90 度，满足加特林的同锥形约束。
    first_dx = first.pos.x - weapon.pos.x
    first_dy = first.pos.y - weapon.pos.y
    second_dx = second.pos.x - weapon.pos.x
    second_dy = second.pos.y - weapon.pos.y
    return first_dx * second_dx + first_dy * second_dy >= 0
