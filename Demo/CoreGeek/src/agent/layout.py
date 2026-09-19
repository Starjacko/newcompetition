from .protocol import Pos, Turn, distance, station_footprint


def base_corner(turn: Turn) -> str | None:
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
    station = turn.station()
    if station is None:
        return ()
    footprint = station_footprint(station.pos)
    occupied = turn.occupied_cells()
    candidates = [
        pos for pos in _ring(footprint)
        if turn.land(pos) and pos not in occupied
    ]
    candidates.sort(key=lambda pos: (_face_distance(turn, pos), pos.x, pos.y))
    return tuple(candidates[:3])


def wall_targets(turn: Turn) -> tuple[tuple[Pos, ...], tuple[Pos, ...], tuple[Pos, ...]]:
    station = turn.station()
    if station is None:
        return (), (), ()
    cells = station_footprint(station.pos)
    xs = [cell.x for cell in cells]
    ys = [cell.y for cell in cells]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    face = attack_face(turn)
    if face == "right":
        front = [Pos(xmax + 2, y) for y in range(ymax, ymin - 1, -1)]
    else:
        front = [Pos(xmin - 2, y) for y in range(ymin, ymax + 1)]
    upper = [Pos(x, ymax + 2) for x in range(xmin - 1, xmax + 2)]
    lower = [Pos(x, ymin - 2) for x in range(xmax + 1, xmin - 2, -1)]
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


def _face_distance(turn: Turn, pos: Pos) -> int:
    station = turn.station()
    if station is None:
        return 0
    if attack_face(turn) == "right":
        return -pos.x
    return pos.x
