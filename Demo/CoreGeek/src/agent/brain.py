from .memory import get_memory
from .planner import Planner


_PLANNER = Planner(get_memory())


def decide(payload: dict) -> dict:
    return _PLANNER.decide(payload)
