#!/usr/bin/env python3
import os
import sys
from pathlib import Path

#1
def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python main3.py <port>")
    port = int(sys.argv[1])
    root = Path(__file__).resolve().parent
    os.chdir(root)
    os.environ.setdefault("AGENT_SOP_FILE", str(root / "logs" / "sop.json"))
    sys.path.insert(0, str(root / "src"))

    from agent.server import serve
    from agent.logging_utils import configure_logging

    logger = configure_logging(root / "logs")

    logger.info("listening on 0.0.0.0:%d", port)
    serve(port)


if __name__ == "__main__":
    main()
