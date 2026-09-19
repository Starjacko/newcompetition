import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .brain import decide
from .logging_utils import event, get_logger

LOGGER = get_logger()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
            response = decide(payload)
            event(
                LOGGER,
                20,
                "http_decision_ok",
                roundNo=payload.get("roundNo"),
                requestBytes=length,
                commandCount=len(response.get("roleCommandMap") or {}),
                promptIssued=bool(response.get("prompt")),
                executeIssued=bool(response.get("executeCmd")),
            )
            body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        except Exception as error:
            event(
                LOGGER,
                40,
                "http_decision_failed",
                roundNo=payload.get("roundNo") if isinstance(locals().get("payload"), dict) else None,
                requestBytes=length,
                errorType=type(error).__name__,
                error=str(error),
                exc_info=True,
            )
            body = b'{"roleCommandMap":{},"prompt":"","executeCmd":""}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(port: int) -> None:
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
