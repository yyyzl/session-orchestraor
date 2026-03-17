from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List


class RuntimeStore:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root
        self.runs_dir = self.runtime_root / "runs"
        self.events_dir = self.runtime_root / "events"
        self.reports_dir = self.runtime_root / "reports"
        self._lock = threading.Lock()
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def snapshot_path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.json"

    def events_path(self, run_id: str) -> Path:
        return self.events_dir / f"{run_id}.ndjson"

    def report_path(self, run_id: str) -> Path:
        return self.reports_dir / f"{run_id}.md"

    def save_snapshot(self, snapshot: Dict[str, Any]) -> None:
        run_id = str(snapshot["run_id"])
        target = self.snapshot_path(run_id)
        encoded = json.dumps(snapshot, ensure_ascii=False, indent=2)
        with self._lock:
            target.write_text(encoded, encoding="utf-8")

    def load_snapshot(self, run_id: str) -> Dict[str, Any]:
        target = self.snapshot_path(run_id)
        with self._lock:
            if not target.exists():
                raise FileNotFoundError(f"run snapshot 不存在: {target}")
            return json.loads(target.read_text(encoding="utf-8"))

    def append_event(self, event: Dict[str, Any]) -> None:
        run_id = str(event["run_id"])
        target = self.events_path(run_id)
        encoded = json.dumps(event, ensure_ascii=False)
        with self._lock:
            with target.open("a", encoding="utf-8") as f:
                f.write(encoded)
                f.write("\n")

    def load_events(self, run_id: str) -> List[Dict[str, Any]]:
        target = self.events_path(run_id)
        with self._lock:
            if not target.exists():
                return []
            events: List[Dict[str, Any]] = []
            for raw in target.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line:
                    continue
                events.append(json.loads(line))
            return events

    def export_report(self, run_id: str) -> Path:
        snapshot = self.load_snapshot(run_id)
        events = self.load_events(run_id)
        lines: List[str] = [
            "# 会话编排运行报告",
            "",
            f"- run_id: {snapshot.get('run_id', '')}",
            f"- task_id: {snapshot.get('task_id', '')}",
            f"- task_type: {snapshot.get('task_type', '')}",
            f"- workflow_mode: {snapshot.get('workflow_mode', '')}",
            f"- status: {snapshot.get('status', '')}",
            f"- phase: {snapshot.get('phase', '')}",
            f"- mode: {snapshot.get('mode', '')}",
            f"- model_id: {snapshot.get('model_id', '')}",
            f"- current_window_index: {snapshot.get('current_window_index', '')}",
            f"- current_round_index_in_window: {snapshot.get('current_round_index_in_window', '')}",
            f"- current_work_item_id: {snapshot.get('current_work_item_id', '')}",
            "",
            "## 事件流水",
            "",
        ]

        for event in events:
            ts = event.get("timestamp", "")
            et = event.get("event_type", "")
            w = event.get("window_index", "")
            r = event.get("round_index_in_window", "")
            g = event.get("global_round_index", "")
            command = str(event.get("command_text", "") or "").strip()
            output = str(event.get("model_output_text", "") or "").strip()
            lines.append(f"- [{ts}] {et} (window={w}, round={r}, global={g})")
            if command:
                lines.append(f"  - command_text: {command}")
            if output:
                lines.append(f"  - model_output_text: {output}")

        target = self.report_path(run_id)
        target.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return target
