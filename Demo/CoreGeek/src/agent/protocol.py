from dataclasses import dataclass, field
from typing import Any

DAY_ROUNDS = 70
NIGHT_ROUNDS = 60
ROUNDS_PER_DAY = DAY_ROUNDS + NIGHT_ROUNDS

WEAPON_BUILD_COST = 25
WALL_MATERIAL = "stone"
LAND = "land"
STATION = "station"
WALL = "wall"
WORKER = "worker"
PIONEER = "pioneer"
TOWER_TYPES = ("gatling", "railgun", "rocket")
CONTROLLABLE_TYPES = (WORKER, PIONEER)
TOWER_RANGE_BY_LEVEL = {
    "gatling": (3, 5, 7),
    "railgun": (6, 8, 10),
    "rocket": (10, 15, 10**9),
}


@dataclass(frozen=True, slots=True)
class Pos:
    x: int
    y: int

    @classmethod
    def load(cls, raw: Any) -> "Pos":
        return cls(int(raw["x"]), int(raw["y"]))

    def dump(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y}


def distance(first: Pos, second: Pos) -> int:
    # 游戏规则使用切比雪夫距离，角色可以向八个方向移动。
    return max(abs(first.x - second.x), abs(first.y - second.y))


def station_footprint(pos: Pos) -> tuple[Pos, ...]:
    return (
        pos,
        Pos(pos.x + 1, pos.y),
        Pos(pos.x, pos.y - 1),
        Pos(pos.x + 1, pos.y - 1),
    )


@dataclass(frozen=True, slots=True)
class Unit:
    unit_id: int
    pos: Pos
    kind: str
    health: int
    level: int
    cooldown: int
    attack_range: int
    capacity: int | None
    backpack: tuple[str, ...]

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "Unit":
        raw_capacity = raw.get("backPackCapability")
        return cls(
            int(raw.get("id") or 0),
            Pos.load(raw["pos"]),
            str(raw["roleType"]),
            int(raw["health"]),
            int(raw.get("level") or 0),
            int(raw.get("cooldown") or 0),
            int(raw.get("attackRange") or 0),
            int(raw_capacity) if raw_capacity is not None else None,
            tuple(str(item) for item in raw.get("backpack") or ()),
        )

    @property
    def backpack_full(self) -> bool:
        if self.capacity is None:
            return False
        return len(self.backpack) >= self.capacity

    def range_of_attack(self) -> int:
        if self.attack_range > 0:
            return self.attack_range
        table = TOWER_RANGE_BY_LEVEL.get(self.kind)
        if table is None:
            return 0
        level = min(max(self.level, 1), len(table))
        return table[level - 1]


@dataclass(frozen=True, slots=True)
class Robot:
    robot_id: int
    pos: Pos
    health: int
    kind: str = ""
    abnormal_state: str = ""
    target_team: str | None = None

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "Robot":
        return cls(
            int(raw["id"]),
            Pos.load(raw["pos"]),
            int(raw["health"]),
            str(raw.get("roleType") or ""),
            str(raw.get("abnormalState") or ""),
            str(raw["targetTeam"]) if raw.get("targetTeam") is not None else None,
        )


@dataclass(frozen=True, slots=True)
class PlayerTask:
    task_type: str
    position: Pos
    cooldown_rounds: int
    score_reward: int
    gold_reward: int
    is_valid: bool
    timeout_rounds: int

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "PlayerTask":
        return cls(
            str(raw.get("taskType") or ""),
            Pos.load(raw["taskPosition"]),
            int(raw.get("coldDownRounds") or 0),
            int(raw.get("scoreReward") or 0),
            int(raw.get("goldReward") or 0),
            bool(raw.get("isValid")),
            int(raw.get("timeoutRounds") or 0),
        )


@dataclass(frozen=True, slots=True)
class WorldNews:
    official: str = ""
    folk: str = ""

    @classmethod
    def load(cls, raw: dict[str, Any] | None) -> "WorldNews":
        raw = raw or {}
        return cls(
            str(raw.get("officialNews") or ""),
            str(raw.get("folkLegends") or ""),
        )


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    code: int
    description: str

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "ErrorInfo":
        return cls(
            int(raw.get("errorCode") or 0),
            str(raw.get("description") or ""),
        )


@dataclass(frozen=True, slots=True)
class Turn:
    round_no: int
    is_day: bool
    gold: int
    width: int
    height: int
    zones: dict[Pos, str]
    ours: tuple[Unit, ...]
    robots: tuple[Robot, ...]
    team_type: str = ""
    team_id: str = ""
    player_tasks: tuple[PlayerTask, ...] = ()
    enemy_roles: tuple[Unit, ...] = ()
    phase_task: str = ""
    last_action_results: dict[int, bool] = field(default_factory=dict)
    last_summon_treasure_result: int = 0
    llm_resp: str = ""
    world_news: WorldNews = field(default_factory=WorldNews)
    last_cmd_result: str = ""
    vendor_shop: dict[str, int] = field(default_factory=dict)
    weapon_shop: dict[str, int] = field(default_factory=dict)
    errors: tuple[ErrorInfo, ...] = ()

    @classmethod
    def load(cls, payload: dict[str, Any]) -> "Turn":
        # 所有外部 JSON 字段在这里归一化，业务模块不直接依赖原始字典。
        round_no = int(payload["roundNo"])
        info = payload["mapInfo"]
        team = payload["teamOur"]
        return cls(
            round_no,
            (round_no - 1) % ROUNDS_PER_DAY < DAY_ROUNDS,
            int(team.get("goldNum") or 0),
            int(info["width"]),
            int(info["height"]),
            {
                Pos.load(zone["pos"]): str(zone["neutralType"])
                for zone in info.get("zones") or ()
            },
            tuple(Unit.load(role) for role in team.get("roles") or ()),
            tuple(
                Robot.load(robot)
                for robot in (payload.get("robot") or {}).get("roles") or ()
            ),
            str(team.get("type") or ""),
            str(team.get("teamId") or ""),
            tuple(
                PlayerTask.load(task)
                for task in team.get("playerTasks") or ()
            ),
            tuple(
                Unit.load(role)
                for role in (payload.get("teamEnemy") or {}).get("roles") or ()
            ),
            str(payload.get("phaseTask") or ""),
            {
                int(key): bool(value)
                for key, value in (payload.get("lastRoundRoleActionResults") or {}).items()
            },
            int(payload.get("lastSummonTreasureResult") or 0),
            str(payload.get("llmResp") or ""),
            WorldNews.load(payload.get("worldNews")),
            str(payload.get("lastCmdResult") or ""),
            {
                str(item.get("name") or ""): int(item.get("price") or 0)
                for item in payload.get("vendorShopList") or ()
                if item.get("name")
            },
            {
                str(item.get("name") or ""): int(item.get("price") or 0)
                for item in payload.get("weaponShopList") or ()
                if item.get("name")
            },
            tuple(
                ErrorInfo.load(error)
                for error in payload.get("errors") or ()
            ),
        )

    def station(self) -> Unit | None:
        for unit in self.ours:
            if unit.kind == STATION:
                return unit
        return None

    def alive(self, kinds: tuple[str, ...]) -> tuple[Unit, ...]:
        return tuple(
            unit for unit in self.ours
            if unit.kind in kinds and unit.health > 0
        )

    def controllable(self) -> tuple[Unit, ...]:
        return tuple(sorted(
            self.alive(CONTROLLABLE_TYPES), key=lambda unit: unit.unit_id,
        ))

    def workers(self) -> tuple[Unit, ...]:
        return tuple(sorted(
            self.alive((WORKER,)), key=lambda unit: unit.unit_id,
        ))

    def weapons(self) -> tuple[Unit, ...]:
        return tuple(sorted(
            self.alive(TOWER_TYPES),
            key=lambda unit: (unit.pos.x, unit.pos.y),
        ))

    def walls(self) -> tuple[Unit, ...]:
        return self.alive((WALL,))

    def stone_mines(self) -> tuple[Pos, ...]:
        return tuple(
            pos for pos, kind in self.zones.items() if kind == WALL_MATERIAL
        )

    def mines(self, kind: str | None = None) -> tuple[Pos, ...]:
        return tuple(
            pos for pos, zone_kind in self.zones.items()
            if zone_kind in {"stone", "iron", "copper"}
            and (kind is None or zone_kind == kind)
        )

    def zones_of(self, kind: str) -> tuple[Pos, ...]:
        return tuple(pos for pos, zone_kind in self.zones.items() if zone_kind == kind)

    def our_robots(self) -> tuple[Robot, ...]:
        return tuple(
            robot for robot in self.robots
            if robot.target_team == self.team_type
        )

    def other_robots(self) -> tuple[Robot, ...]:
        return tuple(
            robot for robot in self.robots
            if robot.target_team is not None and robot.target_team != self.team_type
        )

    def footprint(self, unit: Unit) -> tuple[Pos, ...]:
        if unit.kind == STATION:
            return station_footprint(unit.pos)
        return (unit.pos,)

    def land(self, pos: Pos) -> bool:
        if not 0 <= pos.x < self.width or not 0 <= pos.y < self.height:
            return False
        return self.zones.get(pos, LAND) == LAND

    def occupied_cells(self) -> frozenset[Pos]:
        cells: set[Pos] = set()
        for unit in self.ours:
            cells.update(self.footprint(unit))
        return frozenset(cells)

    def blocked(self, moving: Unit) -> frozenset[Pos]:
        # 矿区、商店、任务点、建筑、角色和机器人都会阻挡移动。
        cells = {pos for pos, kind in self.zones.items() if kind != LAND}
        cells.update(self.occupied_cells())
        cells.discard(moving.pos)
        for robot in self.robots:
            cells.add(robot.pos)
        return frozenset(cells)


def move_command(pos: Pos) -> dict[str, Any]:
    return {"action": "move", "targetPos": [pos.dump()]}


def collect_command(pos: Pos) -> dict[str, Any]:
    return {"action": "collect", "targetPos": [pos.dump()]}


def build_command(pos: Pos, name: str) -> dict[str, Any]:
    return {"action": "build", "targetPos": [pos.dump()], "name": name}


def attack_command(controller_id: int, pos: Pos) -> dict[str, Any]:
    return {
        "action": "attack",
        "targetPos": [pos.dump()],
        "controllerId": str(controller_id),
    }
