#!/usr/bin/env python3
"""Replay docs/request.txt and validate the generated response shape."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / "Demo" / "CoreGeek"
sys.path.insert(0, str(CORE / "src"))

from agent.brain import decide  # noqa: E402


VALID_ACTIONS = {
    "move",
    "attack",
    "sell",
    "buy",
    "build",
    "remove",
    "acceptTask",
    "submitAnswer",
    "summonTreasure",
    "use",
    "drop",
    "collect",
}


def main() -> None:
    request_path = ROOT / "docs" / "request.txt"
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    response = decide(payload)

    assert set(response) == {"roleCommandMap", "prompt", "executeCmd"}
    assert isinstance(response["roleCommandMap"], dict)
    assert isinstance(response["prompt"], str)
    assert isinstance(response["executeCmd"], str)

    for role_id, command in response["roleCommandMap"].items():
        assert str(role_id).isdigit(), role_id
        assert isinstance(command, dict), command
        assert command.get("action") in VALID_ACTIONS, command
        if command["action"] in {
            "move",
            "attack",
            "build",
            "remove",
            "collect",
            "summonTreasure",
        }:
            assert command.get("targetPos"), command
        if command["action"] == "attack":
            assert command.get("controllerId"), command

    print(json.dumps(response, ensure_ascii=False, indent=2))
    print("request-replay-pass")


if __name__ == "__main__":
    main()
