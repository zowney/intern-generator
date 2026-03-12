"""
Local HTTP API for event-by-event generation orchestration.
"""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request

from generator import generate_events, get_last_generation_warning

_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765
_SERVER: ThreadingHTTPServer | None = None
_SERVER_THREAD: threading.Thread | None = None
_SERVER_PORT: int | None = None
_LOCK = threading.Lock()


def _parse_events_payload(content: str | None) -> list[dict]:
    if not content:
        return []
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return []
    events = parsed.get("events")
    return events if isinstance(events, list) else []


def _generate_single_event(payload: dict) -> dict:
    content = ""
    for token in generate_events(
        model=payload["model"],
        project_description=payload["project_description"],
        mode=payload["mode"],
        discipline=payload.get("discipline"),
        num_events=1,
        uploaded_files=None,
        previous_events=payload.get("previous_events"),
        feedback=payload.get("feedback"),
        start_event=int(payload["start_event"]),
        cross_reference=bool(payload.get("cross_reference", False)),
        deliverables_per_event=int(payload.get("deliverables_per_event", 2)),
        codebase_context=payload.get("codebase_context"),
    ):
        content += token
    content = (content or "").strip()
    if not content:
        raise RuntimeError("Generator returned empty JSON content.")
    parsed = json.loads(content)
    events = parsed.get("events")
    if not isinstance(events, list):
        raise RuntimeError("Generator output missing 'events' array.")

    return {
        "content": content,
        "events": events,
        "warning": get_last_generation_warning(),
        "event_generated": int(payload["start_event"]),
        "mode_used": payload["mode"],
    }


def _generate_multievent(payload: dict) -> dict:
    total_events = int(payload["num_events"])
    start_event = int(payload["start_event"])
    current_previous = payload.get("previous_events")
    events_accum: list[dict] = _parse_events_payload(current_previous)
    warnings: list[str] = []

    for offset in range(total_events):
        event_payload = {
            **payload,
            "start_event": start_event + offset,
            "previous_events": current_previous,
        }
        event_result = _generate_single_event(event_payload)
        event_entries = event_result.get("events") or []
        events_accum.extend(event_entries)
        if event_result["warning"]:
            warnings.append(
                f"Event {event_result['event_generated']}: {event_result['warning']}"
            )
        current_previous = (
            json.dumps({"events": events_accum}, ensure_ascii=True)
        )

    return {
        "content": json.dumps({"events": events_accum}, ensure_ascii=True, indent=2),
        "events": events_accum,
        "warning": "\n".join(warnings) if warnings else None,
        "events_generated": total_events,
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
            if self.path in {"/generate-event", "/generate-week"}:
                required = ["model", "project_description", "mode", "start_event"]
                missing = [key for key in required if key not in payload]
                if missing:
                    self._respond(
                        HTTPStatus.BAD_REQUEST,
                        {"error": f"Missing required field(s): {', '.join(missing)}"},
                    )
                    return
                result = _generate_single_event(payload)
                self._respond(HTTPStatus.OK, result)
                return

            if self.path in {"/generate-multievent", "/generate-multiweek"}:
                required = [
                    "model",
                    "project_description",
                    "mode",
                    "start_event",
                    "num_events",
                ]
                missing = [key for key in required if key not in payload]
                if missing:
                    self._respond(
                        HTTPStatus.BAD_REQUEST,
                        {"error": f"Missing required field(s): {', '.join(missing)}"},
                    )
                    return
                result = _generate_multievent(payload)
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


def request_generate_event(payload: dict) -> dict:
    port = start_local_api_server()
    url = f"http://{_HOST}:{port}/generate-event"
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


def request_generate_week(payload: dict) -> dict:
    """Backward-compatible alias for older callers."""
    bridged = dict(payload)
    if "start_week" in bridged and "start_event" not in bridged:
        bridged["start_event"] = bridged["start_week"]
    if "num_weeks" in bridged and "num_events" not in bridged:
        bridged["num_events"] = bridged["num_weeks"]
    return request_generate_event(bridged)
