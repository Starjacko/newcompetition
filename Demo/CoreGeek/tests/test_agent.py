import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from agent.combat import hostile_robots
from agent.protocol import Turn


REQUEST = Path(__file__).parents[3] / "docs" / "request.txt"


def load_payload() -> dict:
    return json.loads(REQUEST.read_text())


def test_response_has_top_level_fields() -> None:
    from agent.brain import decide

    payload = load_payload()
    payload["roundNo"] = 1
    payload["robot"]["roles"] = []
    response = decide(payload)
    assert set(response) == {"roleCommandMap", "prompt", "executeCmd"}


def test_target_team_only_selects_our_robots() -> None:
    payload = load_payload()
    payload["roundNo"] = 71
    robots = payload["robot"]["roles"]
    for robot in robots:
        robot["targetTeam"] = "defender"
    robots[1]["targetTeam"] = "challenger"
    turn = Turn.load(payload)
    assert [robot.robot_id for robot in hostile_robots(turn)] == [robots[1]["id"]]


def test_base_corner_and_mine_parsing() -> None:
    payload = load_payload()
    turn = Turn.load(payload)
    assert turn.team_type == "challenger"
    assert turn.station() is not None
    assert len(turn.mines("stone")) == 2


def test_attack_command_uses_weapon_key_and_controller_id() -> None:
    from agent.brain import decide

    payload = load_payload()
    payload["roundNo"] = 71
    for robot in payload["robot"]["roles"]:
        robot["targetTeam"] = "challenger"
    for role in payload["teamOur"]["roles"]:
        if role["id"] == 10010:
            role["pos"] = {"x": 8, "y": 24}
        elif role["id"] == 10011:
            role["pos"] = {"x": 8, "y": 26}
        elif role["id"] == 10012:
            role["pos"] = {"x": 11, "y": 25}
    response = decide(payload)
    command = response["roleCommandMap"]["10040"]
    assert command["action"] == "attack"
    assert command["controllerId"] == "10010"


def test_structured_decision_log_is_written() -> None:
    from agent.brain import decide
    from agent.logging_utils import configure_logging

    payload = load_payload()
    payload["roundNo"] = 1
    payload["robot"]["roles"] = []
    with tempfile.TemporaryDirectory() as directory:
        configure_logging(directory)
        decide(payload)
        log_text = (Path(directory) / "agent.log").read_text()
    assert '"event":"decision"' in log_text
    assert '"roundNo":1' in log_text
    assert '"commands":' in log_text


def test_repeated_failed_action_enters_recovery_mode() -> None:
    from agent.brain import decide
    from agent.memory import get_memory

    memory = get_memory()
    memory.action_failures.clear()
    payload = load_payload()
    payload["roundNo"] = 1
    payload["robot"]["roles"] = []
    payload["lastRoundRoleActionResults"] = {"10010": False}
    decide(payload)
    payload["roundNo"] = 2
    payload["lastRoundRoleActionResults"] = {"10010": False}
    response = decide(payload)
    assert memory.action_failures[10010] >= 2
    assert response["roleCommandMap"].get("10010", {}).get("action") == "move"


def test_round_restart_clears_runtime_but_keeps_sop() -> None:
    from agent.memory import PersistentMemory
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 20
    payload["lastRoundRoleActionResults"] = {}
    turn = Turn.load(payload)
    memory = PersistentMemory(last_round=19)
    memory.action_failures[10010] = 3
    memory.worker1_phase = "earn"
    memory.sop_library["自进化类1"] = {"attempts": 1}
    memory.update_context(turn)
    assert memory.action_failures[10010] == 3

    payload["roundNo"] = 1
    memory.update_context(Turn.load(payload))
    assert memory.action_failures == {}
    assert memory.worker1_phase == "build_weapons"
    assert "自进化类1" in memory.sop_library


def test_low_gold_worker1_keeps_weapon_priority() -> None:
    from agent.brain import decide

    payload = load_payload()
    payload["roundNo"] = 1
    payload["robot"]["roles"] = []
    payload["teamOur"]["goldNum"] = 0
    for role in payload["teamOur"]["roles"]:
        if role["roleType"] == "gatling":
            role["health"] = 0
        elif role["roleType"] == "railgun":
            role["health"] = 0
        elif role["roleType"] == "rocket":
            role["health"] = 0
    response = decide(payload)
    worker1 = response["roleCommandMap"].get("10010")
    assert worker1 is not None
    assert worker1["action"] in {"move", "collect", "sell"}


def test_invalid_controller_id_is_rejected_without_exception() -> None:
    from agent.commands import validate_for_turn_detailed
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 71
    turn = Turn.load(payload)
    accepted, rejected = validate_for_turn_detailed(
        turn,
        {
            10020: {
                "action": "attack",
                "controllerId": "not-an-id",
                "targetPos": [{"x": 1, "y": 1}],
            }
        },
    )
    assert accepted == {}
    assert rejected


def test_failure_recovery_expires_without_new_failures() -> None:
    from agent.memory import PersistentMemory
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 1
    payload["lastRoundRoleActionResults"] = {"10010": False}
    memory = PersistentMemory(last_round=0)
    memory.update_context(Turn.load(payload))
    payload["roundNo"] = 2
    payload["lastRoundRoleActionResults"] = {"10010": False}
    memory.update_context(Turn.load(payload))
    assert memory.failed_repeatedly(10010, 2)
    payload["roundNo"] = 4
    payload["lastRoundRoleActionResults"] = {}
    memory.update_context(Turn.load(payload))
    assert not memory.failed_repeatedly(10010, 4)
