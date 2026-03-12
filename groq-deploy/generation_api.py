"""
Local HTTP API for week-by-week generation orchestration.
"""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request

from generator import generate_events, get_last_generation_warning

_HOST = "127.0.0.1"
_DEFAULT_PORT = 8865
_SERVER: ThreadingHTTPServer | None = None
_SERVER_THREAD: threading.Thread | None = None
_SERVER_PORT: int | None = None
_LOCK = threading.Lock()


def _generate_single_week(payload: dict) -> dict:
    content = ""
    for token in generate_events(
        model=payload["model"],
        project_description=payload["project_description"],
        mode=payload["mode"],
        discipline=payload.get("discipline"),
        num_weeks=1,
        uploaded_files=None,
        previous_events=payload.get("previous_events"),
        feedback=payload.get("feedback"),
        start_week=int(payload["start_week"]),
        cross_reference=bool(payload.get("cross_reference", False)),
        deliverables_per_event=int(payload.get("deliverables_per_event", 2)),
        codebase_context=payload.get("codebase_context"),
    ):
        content += token

    return {
        "content": content,
        "warning": get_last_generation_warning(),
        "week_generated": int(payload["start_week"]),
        "mode_used": payload["mode"],
    }


def _generate_multiweek(payload: dict) -> dict:
    total_weeks = int(payload["num_weeks"])
    start_week = int(payload["start_week"])
    current_previous = payload.get("previous_events")
    chunks: list[str] = []
    warnings: list[str] = []

    for offset in range(total_weeks):
        week_payload = {
            **payload,
            "start_week": start_week + offset,
            "previous_events": current_previous,
        }
        week_result = _generate_single_week(week_payload)
        content = week_result["content"]
        chunks.append(content)
        if week_result["warning"]:
            warnings.append(
                f"Week {week_result['week_generated']}: {week_result['warning']}"
            )
        current_previous = (
            f"{current_previous}\n\n{content}" if current_previous else content
        )

    return {
        "content": "\n\n".join(chunks),
        "warning": "\n".join(warnings) if warnings else None,
        "weeks_generated": total_weeks,
        "mode_used": payload["mode"],
    }


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._respond(
                HTTPStatus.BAD_REQUEST,
                {"error": "Request body must be valid JSON."},
            )
            return

        try:
            if self.path == "/generate-week":
                required = ["model", "project_description", "mode", "start_week"]
                missing = [key for key in required if key not in payload]
                if missing:
                    self._respond(
                        HTTPStatus.BAD_REQUEST,
                        {"error": f"Missing required field(s): {', '.join(missing)}"},
                    )
                    return
                result = _generate_single_week(payload)
                self._respond(HTTPStatus.OK, result)
                return

            if self.path == "/generate-multiweek":
                required = [
                    "model",
                    "project_description",
                    "mode",
                    "start_week",
                    "num_weeks",
                ]
                missing = [key for key in required if key not in payload]
                if missing:
                    self._respond(
                        HTTPStatus.BAD_REQUEST,
                        {"error": f"Missing required field(s): {', '.join(missing)}"},
                    )
                    return
                result = _generate_multiweek(payload)
                self._respond(HTTPStatus.OK, result)
                return

            self._respond(HTTPStatus.NOT_FOUND, {"error": "Endpoint not found."})
        except Exception as exc:  # pragma: no cover - defensive API boundary
            self._respond(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond(HTTPStatus.OK, {"status": "ok"})
            return
        self._respond(HTTPStatus.NOT_FOUND, {"error": "Endpoint not found."})

    def log_message(self, *_args) -> None:  # pragma: no cover - suppress console noise
        return

    def _respond(self, status: HTTPStatus, body: dict) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def start_local_api_server() -> int:
    global _SERVER, _SERVER_PORT, _SERVER_THREAD
    with _LOCK:
        if _SERVER and _SERVER_THREAD and _SERVER_THREAD.is_alive() and _SERVER_PORT:
            return _SERVER_PORT

        port = _DEFAULT_PORT
        while True:
            try:
                _SERVER = ThreadingHTTPServer((_HOST, port), _Handler)
                _SERVER_PORT = port
                break
            except OSError:
                port += 1

        _SERVER_THREAD = threading.Thread(
            target=_SERVER.serve_forever,
            kwargs={"poll_interval": 0.5},
            daemon=True,
        )
        _SERVER_THREAD.start()
        return _SERVER_PORT


def request_generate_week(payload: dict) -> dict:
    port = start_local_api_server()
    url = f"http://{_HOST}:{port}/generate-week"
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Generation API request failed ({exc.code}): {detail}") from exc
