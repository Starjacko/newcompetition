from .commands import buy, sell, use
from .config import StrategyConfig
from .grid import next_step_near
from .protocol import Pos, Turn, Unit, distance


def move_to(turn: Turn, role: Unit, target: Pos) -> dict | None:
    if distance(role.pos, target) <= 1:
        return None
    step = next_step_near(turn, role, target)
    if step is None:
        return None
    return {"action": "move", "targetPos": [step.dump()]}


def choose_upgrade(
    turn: Turn,
    backpack: tuple[str, ...],
    config: StrategyConfig,
) -> tuple[str, str] | None:
    for item, target_kind in config.upgrade_queue:
        target = upgrade_unit(turn, target_kind)
        if (
            item in backpack
            and target is not None
            and target.level == _required_source_level(item)
        ):
            return item, target_kind
    return None


def upgrade_target(turn: Turn, target_kind: str) -> Pos | None:
    target = upgrade_unit(turn, target_kind)
    return target.pos if target is not None else None


def upgrade_unit(turn: Turn, target_kind: str) -> Unit | None:
    if target_kind == "station":
        return turn.station()
    if target_kind in {"rocket", "railgun", "gatling"}:
        return next(
            (unit for unit in turn.weapons() if unit.kind == target_kind),
            None,
        )
    if target_kind == "front_wall":
        walls = turn.walls()
        return next((wall for wall in walls if wall.level < 3), None)
    return None


def plan_upgrade(turn: Turn, role: Unit, config: StrategyConfig) -> dict | None:
    selected = choose_upgrade(turn, role.backpack, config)
    if selected is None:
        return None
    item, target_kind = selected
    target = upgrade_target(turn, target_kind)
    if target is None:
        # 目标建筑不存在时不发送 use，避免消耗升级券或产生非法动作。
        return None
    if target is not None and distance(role.pos, target) > 1:
        return move_to(turn, role, target)
    return use(item, target)


def sell_backpack(turn: Turn, role: Unit) -> dict | None:
    if not _near_zone(turn, role, "vendor"):
        return None
    for kind in ("iron", "copper", "stone"):
        quantity = role.backpack.count(kind)
        if quantity:
            return sell(kind, quantity)
    return None


def buy_upgrade(turn: Turn, role: Unit, config: StrategyConfig) -> dict | None:
    if not _near_zone(turn, role, "weaponShop"):
        return None
    for item, _target_kind in config.upgrade_queue:
        target = upgrade_unit(turn, _target_kind)
        if target is None or target.level != _required_source_level(item):
            continue
        price = turn.weapon_shop.get(item)
        if price is not None and turn.gold >= price:
            return buy(item)
    return None


def _required_source_level(item: str) -> int:
    if item.endswith("Voucher1"):
        return 1
    if item.endswith("Voucher2"):
        return 2
    return 0


def nearest_zone(turn: Turn, role: Unit, kind: str) -> Pos | None:
    return min(
        turn.zones_of(kind),
        key=lambda pos: (distance(role.pos, pos), pos.x, pos.y),
        default=None,
    )


def _near_zone(turn: Turn, role: Unit, kind: str) -> bool:
    return any(distance(role.pos, pos) <= 1 for pos in turn.zones_of(kind))
