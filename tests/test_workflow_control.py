from __future__ import annotations

import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from orchestrator.models import RunnerStepResult
from orchestrator.service import SessionOrchestrator


class _BaseFakeRunner:
    def __init__(self, *, project_root: Path, **_: object) -> None:
        self.project_root = project_root

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


class _HappyWorkflowRunner(_BaseFakeRunner):
    def run_step(
        self,
        *,
        command_text: str,
        global_round_index: int,
        round_index_in_window: int,
        window_index: int,
        step_id: str,
    ) -> RunnerStepResult:
        if "实现" in command_text:
            target = self.project_root / "book-manage" / "index.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("<!doctype html><title>book-manage</title>", encoding="utf-8")
            return RunnerStepResult(
                model_output_text="实现完成",
                next_command_text="",
                done=True,
                meta={"step_status": "passed"},
            )
        if command_text == "git提交":
            return RunnerStepResult(
                model_output_text="git 提交步骤通过",
                next_command_text="",
                done=False,
                meta={
                    "step_status": "passed",
                    "commit_id": "abc1234",
                    "commit_message": "feat: 增加 book-manage 页面",
                },
            )
        return RunnerStepResult(
            model_output_text=f"{command_text} 已完成",
            next_command_text="",
            done=False,
            meta={"step_status": "passed"},
        )


class _NoChangeRunner(_BaseFakeRunner):
    def run_step(
        self,
        *,
        command_text: str,
        global_round_index: int,
        round_index_in_window: int,
        window_index: int,
        step_id: str,
    ) -> RunnerStepResult:
        done = "实现" in command_text
        return RunnerStepResult(
            model_output_text=f"{command_text} 已处理",
            next_command_text="",
            done=done,
            meta={"step_status": "passed"},
        )


class _NoHandoffRunner(_BaseFakeRunner):
    def run_step(
        self,
        *,
        command_text: str,
        global_round_index: int,
        round_index_in_window: int,
        window_index: int,
        step_id: str,
    ) -> RunnerStepResult:
        if "实现" in command_text:
            target = self.project_root / "book-manage" / "index.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("<!doctype html><title>book-manage</title>", encoding="utf-8")
            return RunnerStepResult(
                model_output_text="实现完成但未结束任务",
                next_command_text="",
                done=False,
                meta={"step_status": "passed"},
            )
        if command_text == "git提交":
            return RunnerStepResult(
                model_output_text="git 提交缺少 handoff 字段",
                next_command_text="",
                done=False,
                meta={"step_status": "passed"},
            )
        return RunnerStepResult(
            model_output_text=f"{command_text} 已完成",
            next_command_text="",
            done=False,
            meta={"step_status": "passed"},
        )


class _HandoffReadyRunner(_BaseFakeRunner):
    def run_step(
        self,
        *,
        command_text: str,
        global_round_index: int,
        round_index_in_window: int,
        window_index: int,
        step_id: str,
    ) -> RunnerStepResult:
        if "实现" in command_text:
            target = self.project_root / "book-manage" / "index.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("<!doctype html><title>book-manage</title>", encoding="utf-8")
            return RunnerStepResult(
                model_output_text="实现完成但仍有后续任务",
                next_command_text="",
                done=False,
                meta={"step_status": "passed"},
            )
        if command_text == "git提交":
            return RunnerStepResult(
                model_output_text="git 提交完成",
                next_command_text="",
                done=False,
                meta={
                    "step_status": "passed",
                    "commit_id": "def5678",
                    "commit_message": "feat: 增加第一窗口产物",
                },
            )
        return RunnerStepResult(
            model_output_text=f"{command_text} 已完成",
            next_command_text="",
            done=False,
            meta={"step_status": "passed"},
        )


class WorkflowControlTests(unittest.TestCase):
    def _init_git_repo(self, root: Path) -> None:
        subprocess.run(
            ["git", "init"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )  # noqa: S603
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )  # noqa: S603
        subprocess.run(
            ["git", "config", "user.name", "tester"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )  # noqa: S603
        (root / ".gitignore").write_text("runtime/\n", encoding="utf-8")
        (root / "README.md").write_text("seed\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "-A"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )  # noqa: S603
        subprocess.run(
            ["git", "commit", "-m", "chore: 增加测试初始化提交"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )  # noqa: S603

    def _wait_status(self, orchestrator: SessionOrchestrator, run_id: str, timeout: float = 8.0) -> dict:
        deadline = time.time() + timeout
        snapshot = {}
        while time.time() < deadline:
            snapshot = orchestrator.get_snapshot(run_id)
            if snapshot.get("status") in {"completed", "failed", "paused", "stopped"}:
                return snapshot
            time.sleep(0.05)
        self.fail(f"run 未在超时内结束: {run_id}, last={snapshot}")

    def test_dev_workflow_executes_full_chain_when_task_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _HappyWorkflowRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t1",
                task_prompt="实现 book-manage 页面",
                task_type="dev",
                mode="mock",
                max_rounds=12,
                max_rounds_per_window=12,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "completed")

            events = orchestrator.get_events(run_id)
            commands = [e["command_text"] for e in events if e.get("event_type") == "step_started"]
            expected = [
                "$start",
                "$before-frontend-dev",
                "实现 book-manage 页面",
                "$check-frontend",
                "$finish-work",
                "git提交",
                "$record-session",
            ]
            self.assertEqual(commands[:7], expected)

    def test_dev_git_commit_requires_code_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _NoChangeRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t2",
                task_prompt="实现但不写文件",
                task_type="dev",
                mode="mock",
                max_rounds=12,
                max_rounds_per_window=12,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertIn(snapshot.get("status"), {"failed", "completed"})

            events = orchestrator.get_events(run_id)
            retry_events = [e for e in events if e.get("event_type") == "step_retrying"]
            self.assertGreaterEqual(len(retry_events), 1)
            git_fail = [
                e
                for e in events
                if e.get("event_type") == "step_finished"
                and e.get("meta", {}).get("failure_code") == "FAIL_NO_CHANGES"
            ]
            self.assertGreaterEqual(len(git_fail), 1)

    def test_dev_handoff_missing_fields_blocks_new_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _NoHandoffRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t3",
                task_prompt="实现并继续下一窗口",
                task_type="dev",
                mode="mock",
                max_rounds=12,
                max_rounds_per_window=12,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "failed")

            events = orchestrator.get_events(run_id)
            blocked = [e for e in events if e.get("event_type") == "handoff_blocked"]
            self.assertGreaterEqual(len(blocked), 1)

    def test_dev_handoff_validated_allows_new_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _HandoffReadyRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t4",
                task_prompt="实现并继续下一窗口",
                task_type="dev",
                mode="mock",
                max_rounds=8,
                max_rounds_per_window=8,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "completed")
            self.assertEqual(int(snapshot.get("current_window_index", 0)), 2)

            events = orchestrator.get_events(run_id)
            handoff_ok = [e for e in events if e.get("event_type") == "handoff_validated"]
            self.assertGreaterEqual(len(handoff_ok), 1)
            policy = [
                e
                for e in events
                if e.get("event_type") == "policy_decision"
                and e.get("meta", {}).get("action") == "start_new_window"
            ]
            self.assertGreaterEqual(len(policy), 1)


if __name__ == "__main__":
    unittest.main()
