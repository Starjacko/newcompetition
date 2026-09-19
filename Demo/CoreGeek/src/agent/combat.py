from .commands import attack, move
from .grid import next_step_near
from .layout import tower_sites
from .protocol import Robot, Turn, Unit, distance


ROLE_WEAPON_PREFERENCE = {
    "worker1": "rocket",
    "pioneer": "railgun",
    "worker2": "gatling",
}


def hostile_robots(turn: Turn) -> tuple[Robot, ...]:
    """Only robots whose targetTeam is ours trigger full-team defence."""
    # Older payloads may omit targetTeam. Be conservative only in that case.
    return tuple(
        robot for robot in turn.robots
        if robot.target_team == turn.team_type or robot.target_team is None
    )


def plan(turn: Turn) -> dict[int, dict]:
    threats = hostile_robots(turn)
    if not threats:
        return {}
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
        if weapon is None:
            continue
        used_weapons.add(weapon.unit_id)
        if distance(controller.pos, weapon.pos) <= 1:
            targets = _targets_for(weapon, threats)
            if targets and weapon.cooldown == 0:
                commands[weapon.unit_id] = attack(controller.unit_id, targets)
        else:
            step = next_step_near(turn, controller, weapon.pos)
            if step is not None:
                commands[controller.unit_id] = move(step)
    return commands


def _controllers_by_preference(
    turn: Turn,
) -> tuple[tuple[Unit, str], ...]:
    workers = turn.workers()
    worker1_id = min((worker.unit_id for worker in workers), default=None)
    worker2_id = max((worker.unit_id for worker in workers), default=None)
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
    count = min(max(weapon.level, 1), len(ranked))
    if weapon.kind not in {"gatling", "rocket"} or count == 1:
        return [robot.pos for robot in ranked[:count]]
    primary = ranked[0]
    selected = [primary]
    for robot in ranked[1:]:
        if len(selected) >= count:
            break
        if all(_same_cone(weapon, existing, robot) for existing in selected):
            selected.append(robot)
    return [robot.pos for robot in selected]


def _same_cone(weapon: Unit, first: Robot, second: Robot) -> bool:
    first_dx = first.pos.x - weapon.pos.x
    first_dy = first.pos.y - weapon.pos.y
    second_dx = second.pos.x - weapon.pos.x
    second_dy = second.pos.y - weapon.pos.y
    return first_dx * second_dx + first_dy * second_dy >= 0
