from .protocol import Pos, Turn, distance, station_footprint


def base_corner(turn: Turn) -> str | None:
    # 基地坐标是基地 2x2 footprint 的左上角。
    station = turn.station()
    if station is None:
        return None
    return "upper_left" if (
        station.pos.x < turn.width / 2 and station.pos.y > turn.height / 2
    ) else "lower_right"


def attack_face(turn: Turn) -> str | None:
    corner = base_corner(turn)
    return "right" if corner == "upper_left" else "left" if corner else None


def tower_sites(turn: Turn) -> tuple[Pos, ...]:
    plan = tower_site_plan(turn)
    return tuple(
        site for kind in ("rocket", "railgun", "gatling")
        if (site := plan.get(kind)) is not None
    )


def tower_site(turn: Turn, kind: str) -> Pos | None:
    return tower_site_plan(turn).get(kind)


def tower_site_plan(turn: Turn) -> dict[str, Pos]:
    station = turn.station()
    if station is None:
        return {}
    footprint = station_footprint(station.pos)
    occupied = turn.occupied_cells()
    front, back, side = _tower_candidate_groups(turn, footprint)
    plan: dict[str, Pos] = {}
    reserved: set[Pos] = set()
    preferences = {
        # 火箭射程最长，放在基地背面可以减少第三座塔把正面通路卡死的概率。
        "rocket": back + side + front,
        "railgun": front + side + back,
        "gatling": front + side + back,
    }
    for kind in ("rocket", "railgun", "gatling"):
        for pos in preferences[kind]:
            if pos in occupied or pos in reserved or not turn.land(pos):
                continue
            plan[kind] = pos
            reserved.add(pos)
            break
    return plan


def wall_targets(turn: Turn) -> tuple[tuple[Pos, ...], tuple[Pos, ...], tuple[Pos, ...]]:
    # 只把主攻面做完整，上下侧墙按比例建设，避免平均铺满浪费 stone。
    station = turn.station()
    if station is None:
        return (), (), ()
    cells = station_footprint(station.pos)
    xs = [cell.x for cell in cells]
    ys = [cell.y for cell in cells]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    face = attack_face(turn)
    # 基地两格宽、两格高。主攻面墙贴着基地外沿布置，避免在基地和墙
    # 之间留下一个会被机器人利用的空档；上下侧墙则交给 workers.py
    # 按从左到右的顺序取一半。
    # 左上基地的主攻面是右侧，右下基地则镜像到左侧。
    if face == "right":
        front = [
            Pos(xmax + 1, y)
            for y in range(ymin - 2, ymax + 3)
        ]
        horizontal_xs = range(xmin - 1, xmax + 2)
    else:
        front = [
            Pos(xmin - 1, y)
            for y in range(ymin - 2, ymax + 3)
        ]
        horizontal_xs = range(xmin - 1, xmax + 2)
    # 上、下两条侧墙都严格按 x 从小到大生成，随后由 _fraction 取左侧一半。
    upper = sorted([
        Pos(x, ymax + 1)
        for x in horizontal_xs
    ], key=lambda pos: (pos.x, pos.y))
    lower = sorted([
        Pos(x, ymin - 1)
        for x in horizontal_xs
    ], key=lambda pos: (pos.x, pos.y))
    return (
        tuple(pos for pos in front if turn.land(pos)),
        tuple(pos for pos in upper if turn.land(pos)),
        tuple(pos for pos in lower if turn.land(pos)),
    )


def _ring(footprint: tuple[Pos, ...]) -> tuple[Pos, ...]:
    result: set[Pos] = set()
    for cell in footprint:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    result.add(Pos(cell.x + dx, cell.y + dy))
    return tuple(result)


def _tower_candidate_groups(
    turn: Turn,
    footprint: tuple[Pos, ...],
) -> tuple[list[Pos], list[Pos], list[Pos]]:
    xs = [cell.x for cell in footprint]
    ys = [cell.y for cell in footprint]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    middle_y = (ymin + ymax) / 2
    ring = list(_ring(footprint))
    if attack_face(turn) == "right":
        front = [pos for pos in ring if pos.x > xmax]
        back = [pos for pos in ring if pos.x < xmin]
    else:
        front = [pos for pos in ring if pos.x < xmin]
        back = [pos for pos in ring if pos.x > xmax]
    side = [pos for pos in ring if xmin <= pos.x <= xmax]
    front.sort(key=lambda pos: (abs(pos.y - middle_y), pos.y, _face_distance(turn, pos)))
    back.sort(key=lambda pos: (abs(pos.y - middle_y), pos.y, pos.x))
    side.sort(key=lambda pos: (abs(pos.y - middle_y), pos.y, pos.x))
    return front, back, side


def _face_distance(turn: Turn, pos: Pos) -> int:
    station = turn.station()
    if station is None:
        return 0
    if attack_face(turn) == "right":
        return -pos.x
    return pos.x
