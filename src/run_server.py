#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time
from pathlib import Path

from orchestrator.service import SessionOrchestrator
from orchestrator.web import SessionOrchestratorHttpServer


def main() -> int:
    parser = argparse.ArgumentParser(description="Session Orchestrator 本地服务")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--project-root",
        type=str,
        default=str(Path(__file__).resolve().parents[1]),
        help="编排器项目根目录，用于定位 runtime 与前端静态资源",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    runtime_root = project_root / "runtime"
    static_root = project_root / "src" / "frontend"
    orchestrator = SessionOrchestrator(
        project_root=project_root,
        runtime_root=runtime_root,
    )
    server = SessionOrchestratorHttpServer(
        host=args.host,
        port=args.port,
        orchestrator=orchestrator,
        static_root=static_root,
    )
    server.start()
    print(f"Session Orchestrator running at http://{args.host}:{args.port}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping server...")
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
