from .commands import build, collect
from .config import StrategyConfig
from .economy import buy_upgrade, move_to, nearest_zone, plan_upgrade, sell_backpack
from .layout import tower_site, wall_targets
from .memory import PersistentMemory
from .protocol import Pos, Turn, Unit, WALL, WEAPON_BUILD_COST, distance, worker_slot


def plan(turn: Turn, memory: PersistentMemory, config: StrategyConfig) -> dict[int, dict]:
    commands: dict[int, dict] = {}
    workers = turn.workers()
    if not workers:
        return commands
    worker1 = next(
        (worker for worker in workers if worker_slot(worker.unit_id) == 1),
        None,
    )
    has_documented_slots = any(
        worker_slot(worker.unit_id) in {1, 2} for worker in workers
    )
    worker1_id = (
        worker1.unit_id
        if worker1 is not None
        else (
            min(worker.unit_id for worker in workers)
            if not has_documented_slots
            else None
        )
    )
    for worker in workers:
        # 工人职责按稳定 ID 绑定，不根据距离临时换岗，保证流水线状态连续。
        command = (
            _worker1(turn, worker, memory, config)
            if worker.unit_id == worker1_id
            else _worker2(turn, worker, memory, config)
        )
        if command is not None:
            commands[worker.unit_id] = command
    return commands


def _worker1(turn: Turn, worker: Unit, memory: PersistentMemory, config: StrategyConfig) -> dict | None:
    existing = {unit.kind for unit in turn.weapons()}
    for kind in config.weapon_build_order:
        if kind in existing:
            continue
        site = tower_site(turn, kind)
        if site is None:
            continue
        memory.worker1_phase = "build_weapons"
        if turn.gold < WEAPON_BUILD_COST:
            # 武器未建完时，金币不足不能提前建墙，必须先恢复赚钱流程。
            memory.worker1_phase = "earn_for_weapons"
            return _earn(turn, worker, config)
        if distance(worker.pos, site) <= 1:
            return build(site, kind)
        return move_to(turn, worker, site)

    front, upper, lower = wall_targets(turn)
    stages = (
        ("build_front_wall", front),
        ("build_upper_wall", _fraction(upper, config.upper_wall_ratio)),
        ("build_lower_wall", _fraction(lower, config.lower_wall_ratio)),
    )
    built_walls = {unit.pos for unit in turn.walls()}
    for phase, targets in stages:
        missing = [target for target in targets if target not in built_walls]
        if not missing:
            continue
        memory.worker1_phase = phase
        desired_batch = min(config.stone_batch_size, len(missing))
        stones = worker.backpack.count("stone")
        if memory.worker1_wall_stage != phase:
            memory.worker1_wall_stage = phase
            memory.worker1_batch_goal = None
            memory.worker1_building_batch = False
        if memory.worker1_building_batch:
            # 一旦凑够一批石头，连续建造直到本批石头耗尽。
            if stones <= 0:
                memory.worker1_building_batch = False
            else:
                target = missing[0]
                if distance(worker.pos, target) <= 1:
                    return build(target, WALL)
                return move_to(turn, worker, target)
        if memory.worker1_batch_goal is None:
            memory.worker1_batch_goal = desired_batch
        if stones >= memory.worker1_batch_goal:
            memory.worker1_batch_goal = None
            memory.worker1_building_batch = True
            target = missing[0]
            if distance(worker.pos, target) <= 1:
                return build(target, WALL)
            return move_to(turn, worker, target)
        mine = _nearest_mine(turn, worker, "stone")
        if mine is None:
            return None
        if distance(worker.pos, mine) <= 1:
            return collect(mine)
        return move_to(turn, worker, mine)

    memory.worker1_phase = "earn"
    return _earn(turn, worker, config)


def _worker2(turn: Turn, worker: Unit, memory: PersistentMemory, config: StrategyConfig) -> dict | None:
    has_ore = _has_ore(worker)
    ready_to_sell = _ready_to_sell(turn, worker, memory)

    if has_ore and ready_to_sell:
        # 一个矿采完、矿点消失或背包满后，才进入卖矿流程。
        sold = sell_backpack(turn, worker)
        if sold is not None:
            memory.worker2_phase = "sell"
            return sold
        vendor = nearest_zone(turn, worker, "vendor")
        if vendor is not None:
            memory.worker2_phase = "sell"
            return move_to(turn, worker, vendor)
        # 没有找到小贩时不能跳过卖矿直接买券或继续采矿。
        return None

    # 只有当前矿批次已经卖空后，才按队列购买并使用升级券。
    if not has_ore:
        upgrade = plan_upgrade(turn, worker, config)
        if upgrade is not None:
            memory.worker2_phase = "upgrade"
            return upgrade

    if memory.worker2_phase == "sell":
        shop = nearest_zone(turn, worker, "weaponShop")
        if shop is not None and distance(worker.pos, shop) > 1:
            return move_to(turn, worker, shop)
        bought = buy_upgrade(turn, worker, config)
        if bought is not None:
            memory.worker2_phase = "buy_upgrade"
            return bought
        memory.worker2_phase = "mine"

    mine = memory.worker2_mine
    if mine not in turn.mines():
        mine = _choose_mine(turn, worker, config)
        memory.worker2_mine = mine
        memory.worker2_mine_collects = 0
    if mine is None:
        return None
    memory.worker2_phase = "mine"
    if distance(worker.pos, mine) <= 1:
        # collect 每次只采 1 个资源，成功次数由下一回合结果写回 memory。
        return collect(mine)
    return move_to(turn, worker, mine)


def _ready_to_sell(turn: Turn, worker: Unit, memory: PersistentMemory) -> bool:
    if not _has_ore(worker):
        return False
    if memory.worker2_mine is None:
        return True
    if worker.backpack_full:
        return True
    if memory.worker2_mine_collects >= 10:
        return True
    return memory.worker2_mine is not None and memory.worker2_mine not in turn.mines()


def _earn(turn: Turn, worker: Unit, config: StrategyConfig) -> dict | None:
    if _has_ore(worker):
        sold = sell_backpack(turn, worker)
        if sold is not None:
            return sold
        vendor = nearest_zone(turn, worker, "vendor")
        return move_to(turn, worker, vendor) if vendor else None
    mine = _choose_mine(turn, worker, config)
    if mine is None:
        return None
    if distance(worker.pos, mine) <= 1:
        return collect(mine)
    return move_to(turn, worker, mine)


def _has_ore(worker: Unit) -> bool:
    return any(item in {"stone", "iron", "copper"} for item in worker.backpack)


def _nearest_mine(turn: Turn, worker: Unit, kind: str) -> Pos | None:
    return min(
        turn.mines(kind),
        key=lambda pos: (distance(worker.pos, pos), pos.x, pos.y),
        default=None,
    )


def _choose_mine(turn: Turn, worker: Unit, config: StrategyConfig) -> Pos | None:
    ranked_kinds = sorted(
        config.vendor_mine_order,
        key=lambda kind: (
            -turn.vendor_shop.get(kind, 0),
            config.vendor_mine_order.index(kind),
        ),
    )
    for kind in ranked_kinds:
        mine = _nearest_mine(turn, worker, kind)
        if mine is not None:
            return mine
    return None


def _fraction(targets: tuple[Pos, ...], ratio: float) -> tuple[Pos, ...]:
    if not targets:
        return ()
    count = max(1, int(len(targets) * ratio))
    return targets[:count]
