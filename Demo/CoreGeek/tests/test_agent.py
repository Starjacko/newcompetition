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


def test_rocket_tower_site_is_behind_upper_left_base() -> None:
    from agent.layout import tower_site
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 1
    payload["robot"]["roles"] = []
    payload["teamOur"]["roles"] = [
        role for role in payload["teamOur"]["roles"]
        if role["roleType"] not in {"gatling", "railgun", "rocket"}
    ]
    turn = Turn.load(payload)
    station = turn.station()
    site = tower_site(turn, "rocket")
    assert station is not None
    assert site is not None
    assert site.x < station.pos.x


def test_upper_left_wall_targets_have_requested_counts() -> None:
    from agent.layout import wall_targets
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 1
    turn = Turn.load(payload)
    front, upper, lower = wall_targets(turn)
    station = turn.station()
    assert station is not None
    assert len(front) == 6
    assert len(upper) == 4
    assert len(lower) == 4
    assert all(pos.x > station.pos.x for pos in front)


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


def test_worker1_batch_state_stays_in_build_phase() -> None:
    from agent.config import DEFAULT_CONFIG
    from agent.memory import PersistentMemory
    from agent.protocol import Turn
    from agent.workers import _worker1

    payload = load_payload()
    payload["roundNo"] = 1
    payload["robot"]["roles"] = []
    payload["teamOur"]["goldNum"] = 0
    worker = next(
        role for role in payload["teamOur"]["roles"]
        if role["id"] == 10010
    )
    worker["backpack"] = ["stone"] * 6
    turn = Turn.load(payload)
    memory = PersistentMemory()
    command = _worker1(turn, turn.workers()[0], memory, DEFAULT_CONFIG)
    assert command is not None
    assert memory.worker1_building_batch is True


def test_worker2_does_not_sell_before_mine_is_finished() -> None:
    from agent.config import DEFAULT_CONFIG
    from agent.memory import PersistentMemory
    from agent.protocol import Turn
    from agent.workers import _worker2

    payload = load_payload()
    payload["roundNo"] = 1
    payload["robot"]["roles"] = []
    worker = next(
        role for role in payload["teamOur"]["roles"]
        if role["id"] == 10012
    )
    worker["backpack"] = ["iron"]
    turn = Turn.load(payload)
    memory = PersistentMemory(
        worker2_mine=next(iter(turn.mines("iron"))),
        worker2_mine_collects=1,
    )
    command = _worker2(turn, turn.workers()[1], memory, DEFAULT_CONFIG)
    assert command is not None
    assert command["action"] in {"move", "collect"}


def test_worker2_sells_before_using_upgrade_voucher() -> None:
    from agent.config import StrategyConfig
    from agent.memory import PersistentMemory
    from agent.protocol import Turn
    from agent.workers import _worker2

    payload = load_payload()
    payload["roundNo"] = 1
    payload["robot"]["roles"] = []
    payload["teamOur"]["goldNum"] = 100
    worker = next(
        role for role in payload["teamOur"]["roles"]
        if role["id"] == 10012
    )
    worker["backpack"] = ["iron", "WeaponUpgradeVoucher1"]
    turn = Turn.load(payload)
    memory = PersistentMemory(
        worker2_mine=next(iter(turn.mines("iron"))),
        worker2_mine_collects=10,
    )
    command = _worker2(turn, turn.workers()[1], memory, StrategyConfig())
    assert command is not None
    assert command["action"] in {"move", "sell"}


def test_night_defence_returns_unassigned_worker_to_station() -> None:
    from agent.brain import decide

    payload = load_payload()
    payload["roundNo"] = 71
    payload["robot"]["roles"] = [{
        "id": 90001,
        "pos": {"x": 39, "y": 30},
        "roleType": "smallRobot",
        "health": 100,
        "targetTeam": "challenger",
    }]
    payload["teamOur"]["roles"] = [
        role for role in payload["teamOur"]["roles"]
        if role["roleType"] in {"station", "worker", "pioneer", "rocket"}
    ]
    response = decide(payload)
    commands = response["roleCommandMap"]
    assert commands["10010"]["action"] == "move"
    assert commands["10011"]["action"] == "move"
    assert commands["10012"]["action"] == "move"


def test_active_task_keeps_pioneer_from_night_defence() -> None:
    from agent.config import DEFAULT_CONFIG
    from agent.memory import PersistentMemory
    from agent.planner import Planner

    payload = load_payload()
    payload["roundNo"] = 71
    payload["phaseTask"] = "请查询样例数据并回答。"
    payload["llmResp"] = ""
    payload["lastCmdResult"] = ""
    for robot in payload["robot"]["roles"]:
        robot["targetTeam"] = "challenger"
    planner = Planner(PersistentMemory(task_position=None), DEFAULT_CONFIG)
    response = planner.decide(payload)
    assert response["prompt"]
    assert "10011" not in response["roleCommandMap"]


def test_active_task_answer_is_submitted_even_during_defence() -> None:
    from agent.config import DEFAULT_CONFIG
    from agent.memory import PersistentMemory
    from agent.planner import Planner

    payload = load_payload()
    payload["roundNo"] = 71
    payload["phaseTask"] = "请回答 40+2。"
    payload["llmResp"] = "ANSWER: 42"
    for robot in payload["robot"]["roles"]:
        robot["targetTeam"] = "challenger"
    planner = Planner(PersistentMemory(task_position=None), DEFAULT_CONFIG)
    response = planner.decide(payload)
    command = response["roleCommandMap"]["10011"]
    assert command == {"action": "submitAnswer", "taskAnswer": "42"}


def test_duplicate_move_targets_are_deduped() -> None:
    from agent.config import DEFAULT_CONFIG
    from agent.memory import PersistentMemory
    from agent.planner import Planner
    from agent.protocol import Turn

    payload = load_payload()
    turn = Turn.load(payload)
    planner = Planner(PersistentMemory(), DEFAULT_CONFIG)
    commands = planner._dedupe_move_targets(
        turn,
        {
            10010: {"action": "move", "targetPos": [{"x": 6, "y": 22}]},
            10012: {"action": "move", "targetPos": [{"x": 6, "y": 22}]},
            10011: {"action": "move", "targetPos": [{"x": 9, "y": 13}]},
        },
    )
    targets = [
        tuple(command["targetPos"][0].values())
        for command in commands.values()
        if command["action"] == "move"
    ]
    assert len(targets) == len(set(targets))


def test_active_task_uses_successful_cmd_output_for_answer_prompt() -> None:
    from agent.memory import PersistentMemory
    from agent.pioneer import plan
    from agent.protocol import Turn

    payload = load_payload()
    payload["phaseTask"] = "请根据文件输出回答。"
    payload["lastCmdResult"] = "[exitCode:0]\nresult=42"
    payload["llmResp"] = ""
    turn = Turn.load(payload)
    pioneer = next(unit for unit in turn.ours if unit.kind == "pioneer")
    decision = plan(turn, pioneer, PersistentMemory(), None)
    assert "result=42" in decision.prompt


def test_malformed_command_fields_are_rejected() -> None:
    from agent.commands import validate_commands

    accepted = validate_commands({
        10010: {"action": "move", "targetPos": [{"x": "1", "y": 1}]},
        10011: {"action": "summonTreasure", "targetPos": [{"x": 1, "y": 1}]},
        10012: {"action": "submitAnswer", "taskAnswer": ""},
    })
    assert accepted == {}


def test_remove_is_not_artificially_limited_to_daytime() -> None:
    from agent.commands import validate_for_turn
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 71
    worker = next(
        role for role in payload["teamOur"]["roles"] if role["id"] == 10010
    )
    worker["pos"] = {"x": 5, "y": 22}
    turn = Turn.load(payload)
    accepted = validate_for_turn(
        turn,
        {
            10010: {
                "action": "remove",
                "targetPos": [{"x": 5, "y": 21}],
            }
        },
    )
    assert accepted[10010]["action"] == "remove"


def test_remove_requires_an_actual_wall_target() -> None:
    from agent.commands import validate_for_turn
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 71
    worker = next(
        role for role in payload["teamOur"]["roles"] if role["id"] == 10010
    )
    worker["pos"] = {"x": 5, "y": 22}
    turn = Turn.load(payload)
    accepted = validate_for_turn(
        turn,
        {
            10010: {
                "action": "remove",
                "targetPos": [{"x": 5, "y": 22}],
            }
        },
    )
    assert accepted == {}


def test_worker_slot_does_not_change_when_worker1_is_dead() -> None:
    from agent.config import DEFAULT_CONFIG
    from agent.memory import PersistentMemory
    from agent.protocol import Turn
    from agent.workers import plan

    payload = load_payload()
    payload["roundNo"] = 1
    payload["robot"]["roles"] = []
    for role in payload["teamOur"]["roles"]:
        if role["id"] == 10010:
            role["health"] = 0
    turn = Turn.load(payload)
    memory = PersistentMemory()
    commands = plan(turn, memory, DEFAULT_CONFIG)
    assert memory.worker1_phase == "build_weapons"
    assert commands.get(10012, {}).get("action") in {
        "move", "collect", "sell", "buy", "use",
    }


def test_attack_requires_controller_near_tower() -> None:
    from agent.commands import validate_for_turn
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 71
    turn = Turn.load(payload)
    accepted = validate_for_turn(
        turn,
        {
            10040: {
                "action": "attack",
                "controllerId": "10010",
                "targetPos": [{"x": 4, "y": 4}],
            }
        },
    )
    assert accepted == {}


def test_use_requires_target_for_targeted_items() -> None:
    from agent.commands import validate_for_turn
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 1
    worker = next(
        role for role in payload["teamOur"]["roles"] if role["id"] == 10010
    )
    worker["pos"] = {"x": 5, "y": 22}
    turn = Turn.load(payload)
    accepted = validate_for_turn(
        turn,
        {
            10010: {
                "action": "use",
                "name": "WallFixer",
                "targetPos": [{"x": 5, "y": 21}],
            },
            10011: {"action": "use", "name": "Medicine"},
        },
    )
    assert accepted == {
        10010: {
            "action": "use",
            "name": "WallFixer",
            "targetPos": [{"x": 5, "y": 21}],
        },
        10011: {"action": "use", "name": "Medicine"},
    }


def test_use_rejects_missing_or_wrong_building_target() -> None:
    from agent.commands import validate_for_turn
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 1
    worker = next(
        role for role in payload["teamOur"]["roles"] if role["id"] == 10010
    )
    worker["pos"] = {"x": 5, "y": 22}
    turn = Turn.load(payload)
    accepted = validate_for_turn(
        turn,
        {
            10010: {"action": "use", "name": "WallFixer"},
            10011: {
                "action": "use",
                "name": "WeaponUpgradeVoucher1",
                "targetPos": [{"x": 5, "y": 21}],
            },
        },
    )
    assert accepted == {}


def test_use_allows_optional_target_for_non_targeted_items() -> None:
    from agent.commands import validate_for_turn
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 1
    turn = Turn.load(payload)
    accepted = validate_for_turn(
        turn,
        {
            10011: {
                "action": "use",
                "name": "Medicine",
                "targetPos": [{"x": 1, "y": 1}],
            }
        },
    )
    assert accepted[10011]["action"] == "use"


def test_attack_rejects_out_of_range_target() -> None:
    from agent.commands import validate_for_turn
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 71
    worker = next(
        role for role in payload["teamOur"]["roles"] if role["id"] == 10010
    )
    worker["pos"] = {"x": 8, "y": 24}
    turn = Turn.load(payload)
    accepted = validate_for_turn(
        turn,
        {
            10020: {
                "action": "attack",
                "controllerId": "10010",
                "targetPos": [{"x": 30, "y": 30}],
            }
        },
    )
    assert accepted == {}


def test_gatling_rejects_targets_outside_same_cone() -> None:
    from agent.commands import validate_for_turn
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 71
    worker = next(
        role for role in payload["teamOur"]["roles"] if role["id"] == 10010
    )
    gatling = next(
        role for role in payload["teamOur"]["roles"] if role["id"] == 10020
    )
    worker["pos"] = {"x": 8, "y": 24}
    gatling["level"] = 2
    gatling["attackRange"] = 5
    turn = Turn.load(payload)
    accepted = validate_for_turn(
        turn,
        {
            10020: {
                "action": "attack",
                "controllerId": "10010",
                "targetPos": [{"x": 13, "y": 24}, {"x": 5, "y": 24}],
            }
        },
    )
    assert accepted == {}


def test_only_worker2_collects_count_toward_worker2_mine() -> None:
    from agent.memory import PersistentMemory
    from agent.protocol import Turn

    payload = load_payload()
    payload["roundNo"] = 1
    payload["lastRoundRoleActionResults"] = {}
    turn = Turn.load(payload)
    mine = next(iter(turn.mines("stone")))
    memory = PersistentMemory(
        worker2_mine=mine,
        last_plans={
            10010: {"action": "collect", "targetPos": [mine.dump()]},
            10012: {"action": "collect", "targetPos": [mine.dump()]},
        },
    )
    payload["roundNo"] = 2
    payload["lastRoundRoleActionResults"] = {"10010": True, "10012": True}
    memory.update_context(Turn.load(payload))
    assert memory.worker2_mine_collects == 1


def test_empty_sop_observation_does_not_increase_attempts() -> None:
    from agent.memory import PersistentMemory

    memory = PersistentMemory()
    memory.remember_sop("自进化类1")
    assert memory.sop_library == {}
