from typing import Any

from .protocol import Turn


def role_snapshot(turn: Turn) -> list[dict[str, Any]]:
    return [
        {
            "id": role.unit_id,
            "kind": role.kind,
            "x": role.pos.x,
            "y": role.pos.y,
            "health": role.health,
            "level": role.level,
            "backpack": len(role.backpack),
        }
        for role in turn.ours
        if role.kind in {"worker", "pioneer"}
    ]


def command_snapshot(commands: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for role_id, command in sorted(commands.items()):
        item = {
            "roleId": role_id,
            "action": command.get("action"),
        }
        if command.get("name"):
            item["name"] = command["name"]
        if command.get("controllerId"):
            item["controllerId"] = command["controllerId"]
        targets = command.get("targetPos") or []
        if targets:
            item["targetPos"] = targets
        if command.get("num") is not None:
            item["num"] = command["num"]
        result.append(item)
    return result


def turn_snapshot(turn: Turn) -> dict[str, Any]:
    hostile = [
        robot for robot in turn.robots
        if robot.target_team == turn.team_type or robot.target_team is None
    ]
    unknown = [robot.robot_id for robot in turn.robots if robot.target_team is None]
    return {
        "roundNo": turn.round_no,
        "day": turn.is_day,
        "team": turn.team_type,
        "gold": turn.gold,
        "robotCount": len(turn.robots),
        "hostileRobotCount": len(hostile),
        "hostileRobotIds": [robot.robot_id for robot in hostile],
        "unknownRobotIds": unknown,
        "weaponCount": len(turn.weapons()),
        "wallCount": len(turn.walls()),
        "taskActive": bool(turn.phase_task),
        "taskPointCount": len(turn.player_tasks),
        "errors": [
            {"code": error.code, "description": error.description}
            for error in turn.errors
        ],
        "lastActionResults": turn.last_action_results,
    }
