from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen

from orchestrator.service import SessionOrchestrator
from orchestrator.web import SessionOrchestratorHttpServer


class WebStaticMountTests(unittest.TestCase):
    def _start_server(self, root: Path) -> SessionOrchestratorHttpServer:
        orchestrator = SessionOrchestrator(
            project_root=root,
            runtime_root=root / "runtime",
            runner_factory_map={"mock": object},
        )
        server = SessionOrchestratorHttpServer(
            host="127.0.0.1",
            port=0,
            orchestrator=orchestrator,
            static_root=root / "src" / "frontend",
        )
        server.start()
        return server

    @staticmethod
    def _url(server: SessionOrchestratorHttpServer, path: str) -> str:
        port = int(server._httpd.server_address[1])  # type: ignore[union-attr]
        return f"http://127.0.0.1:{port}{path}"

    def test_root_frontend_page_still_served(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frontend_dir = root / "src" / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=True)
            (frontend_dir / "index.html").write_text("<!doctype html><title>console</title>", encoding="utf-8")

            server = self._start_server(root)
            try:
                with urlopen(self._url(server, "/"), timeout=3) as response:  # noqa: S310
                    body = response.read().decode("utf-8")
                self.assertIn("console", body)
            finally:
                server.stop()

    def test_book_manage_page_can_be_served(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frontend_dir = root / "src" / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=True)
            (frontend_dir / "index.html").write_text("<!doctype html><title>console</title>", encoding="utf-8")
            app_dir = root / "book-manage"
            app_dir.mkdir(parents=True, exist_ok=True)
            (app_dir / "index.html").write_text("<!doctype html><title>book-manage</title>", encoding="utf-8")

            server = self._start_server(root)
            try:
                with urlopen(self._url(server, "/book-manage/index.html"), timeout=3) as response:  # noqa: S310
                    body = response.read().decode("utf-8")
                self.assertIn("book-manage", body)
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()
