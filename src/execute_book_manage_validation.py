#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from orchestrator.service import SessionOrchestrator
from orchestrator.validation import validate_run_consistency


def main() -> int:
    parser = argparse.ArgumentParser(description="执行 book-manage 编排验证并导出报告")
    parser.add_argument(
        "--project-root",
        type=str,
        default=str(Path(__file__).resolve().parents[1]),
    )
    parser.add_argument("--mode", type=str, default="mock", choices=["mock", "real"])
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument(
        "--workspace-project-root",
        type=str,
        default="",
        help="目标 Git 仓库根目录（留空默认当前 project-root）",
    )
    parser.add_argument(
        "--git-scope-path",
        type=str,
        default="book-manage/",
        help="本轮实现与提交的作用域路径（仓库内相对路径）",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    runtime_root = project_root / "runtime"
    orchestrator = SessionOrchestrator(
        project_root=project_root,
        runtime_root=runtime_root,
    )

    run_id = orchestrator.start_run(
        task_id="book-manage-validation",
        task_prompt="实现 book-manage 前端（查看/新增/删除），并完成 localStorage 持久化。",
        task_type="dev",
        mode=args.mode,
        max_rounds=8,
        max_rounds_per_window=2,
        workspace_project_root=args.workspace_project_root or None,
        git_scope_path=args.git_scope_path or None,
    )
    print(f"run_id={run_id}")

    deadline = time.time() + args.timeout_seconds
    snapshot = {}
    while time.time() < deadline:
        snapshot = orchestrator.get_snapshot(run_id)
        if snapshot.get("status") in {"completed", "failed", "stopped"}:
            break
        time.sleep(0.2)

    report_path = orchestrator.export_report(run_id)
    consistency = validate_run_consistency(runtime_root=runtime_root, run_id=run_id)
    print(json.dumps({"snapshot": snapshot, "report_path": str(report_path), "consistency": consistency}, ensure_ascii=False, indent=2))
    return 0 if consistency["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
