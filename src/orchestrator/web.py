from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from .service import SessionOrchestrator


def _read_json_body(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


class SessionOrchestratorHttpServer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        orchestrator: SessionOrchestrator,
        static_root: Path,
    ) -> None:
        self.host = host
        self.port = port
        self.orchestrator = orchestrator
        self.static_root = static_root
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        handler_cls = self._build_handler()
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler_cls)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _build_handler(self):
        orchestrator = self.orchestrator
        static_root = self.static_root
        book_manage_root = orchestrator.project_root / "book-manage"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                try:
                    parsed = urlparse(self.path)
                    path = parsed.path
                    if path == "/api/health":
                        return self._json(200, {"status": "ok"})

                    if path == "/favicon.ico":
                        candidate = (static_root / "favicon.ico").resolve()
                        if candidate.exists() and candidate.is_file():
                            return self._serve_static(path)
                        self.send_response(204)
                        self.end_headers()
                        return None

                    if path.startswith("/api/runs/") and path.endswith("/events"):
                        run_id = path[len("/api/runs/") : -len("/events")].strip("/")
                        query = parse_qs(parsed.query)
                        since = int((query.get("since") or ["0"])[0])
                        events = orchestrator.get_events(run_id, since_seq=since)
                        next_since = since
                        if events:
                            next_since = int(max(event.get("event_seq", 0) for event in events))
                        return self._json(200, {"events": events, "next_since": next_since})

                    if path.startswith("/api/runs/") and path.endswith("/report"):
                        run_id = path[len("/api/runs/") : -len("/report")].strip("/")
                        report_path = orchestrator.export_report(run_id)
                        content = report_path.read_text(encoding="utf-8")
                        return self._json(
                            200,
                            {
                                "run_id": run_id,
                                "report_path": str(report_path),
                                "report_markdown": content,
                            },
                        )

                    if path.startswith("/api/runs/"):
                        run_id = path[len("/api/runs/") :].strip("/")
                        snapshot = orchestrator.get_snapshot(run_id)
                        return self._json(200, snapshot)

                    if path == "/book-manage" or path.startswith("/book-manage/"):
                        return self._serve_static(
                            path,
                            static_override=book_manage_root,
                            mount_prefix="/book-manage",
                        )

                    return self._serve_static(path)
                except KeyError as exc:
                    return self._json(404, {"error": str(exc)})
                except FileNotFoundError as exc:
                    return self._json(404, {"error": str(exc)})
                except Exception as exc:  # noqa: BLE001
                    return self._json(500, {"error": str(exc)})

            def do_POST(self):  # noqa: N802
                try:
                    parsed = urlparse(self.path)
                    path = parsed.path
                    if path == "/api/runs/start":
                        body = _read_json_body(self)
                        run_id = orchestrator.start_run(
                            task_id=str(body.get("task_id") or "session-task"),
                            task_prompt=str(body.get("task_prompt") or ""),
                            task_type=str(body.get("task_type") or "dev"),
                            mode=str(body.get("mode") or "mock"),
                            model_id=str(body.get("model_id") or "gpt-5.3-codex"),
                            reasoning_level=str(body.get("reasoning_level") or "medium"),
                            max_rounds=int(body.get("max_rounds") or 6),
                            max_rounds_per_window=int(body.get("max_rounds_per_window") or 3),
                            step_delay_seconds=float(body.get("step_delay_seconds") or 0.0),
                            step_max_retry=int(body.get("step_max_retry") or 1),
                            codex_bin=body.get("codex_bin"),
                        )
                        return self._json(200, {"run_id": run_id})

                    if path.startswith("/api/runs/") and path.endswith("/operator-message"):
                        run_id = path[len("/api/runs/") : -len("/operator-message")].strip("/")
                        body = _read_json_body(self)
                        orchestrator.send_operator_message(
                            run_id,
                            operator_id=str(body.get("operator_id") or "human"),
                            text=str(body.get("text") or ""),
                        )
                        return self._json(200, {"ok": True})

                    if path.startswith("/api/runs/") and path.endswith("/stop"):
                        run_id = path[len("/api/runs/") : -len("/stop")].strip("/")
                        orchestrator.stop_run(run_id)
                        return self._json(200, {"ok": True})

                    return self._json(404, {"error": "not found"})
                except KeyError as exc:
                    return self._json(404, {"error": str(exc)})
                except ValueError as exc:
                    return self._json(400, {"error": str(exc)})
                except RuntimeError as exc:
                    return self._json(409, {"error": str(exc)})
                except Exception as exc:  # noqa: BLE001
                    return self._json(500, {"error": str(exc)})

            def _serve_static(
                self,
                path: str,
                *,
                static_override: Optional[Path] = None,
                mount_prefix: str = "",
            ):
                effective_root = (static_override or static_root).resolve()
                normalized_path = path
                if mount_prefix and path.startswith(mount_prefix):
                    normalized_path = path[len(mount_prefix) :]

                normalized = normalized_path.strip("/") or "index.html"
                if normalized == "":
                    normalized = "index.html"
                if normalized == "index":
                    normalized = "index.html"
                target = (effective_root / normalized).resolve()
                try:
                    target.relative_to(effective_root)
                except ValueError:
                    return self._json(403, {"error": "forbidden"})

                if not target.exists() or not target.is_file():
                    if "." not in normalized:
                        fallback = (effective_root / "index.html").resolve()
                        if fallback.exists() and fallback.is_file():
                            target = fallback
                        else:
                            return self._json(404, {"error": "static file not found"})
                    else:
                        return self._json(404, {"error": "static file not found"})

                if not target.exists() or not target.is_file():
                    return self._json(404, {"error": "static file not found"})

                content_type = "text/plain; charset=utf-8"
                if target.suffix == ".html":
                    content_type = "text/html; charset=utf-8"
                if target.suffix == ".js":
                    content_type = "application/javascript; charset=utf-8"
                if target.suffix == ".css":
                    content_type = "text/css; charset=utf-8"

                payload = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return None

            def _json(self, code: int, payload: Dict[str, Any]):
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return None

            def log_message(self, format, *args):  # noqa: A003
                return None

        return Handler
