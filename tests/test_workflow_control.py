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


class _RealNoCommitRunner(_BaseFakeRunner):
    def run_step(
        self,
        *,
        command_text: str,
        global_round_index: int,
        round_index_in_window: int,
        window_index: int,
        step_id: str,
    ) -> RunnerStepResult:
        if "完成任务" in command_text:
            target = self.project_root / "book-manage" / "index.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("<!doctype html><title>counter</title>", encoding="utf-8")
            return RunnerStepResult(
                model_output_text="实现完成",
                next_command_text="",
                done=True,
                meta={"step_status": "passed"},
            )
        if "git 提交" in command_text or "git提交" in command_text:
            return RunnerStepResult(
                model_output_text="我只能提供命令，不能替你提交。",
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


class _RealCommitRunner(_BaseFakeRunner):
    def run_step(
        self,
        *,
        command_text: str,
        global_round_index: int,
        round_index_in_window: int,
        window_index: int,
        step_id: str,
    ) -> RunnerStepResult:
        if "完成任务" in command_text:
            target = self.project_root / "book-manage" / "index.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("<!doctype html><title>counter</title>", encoding="utf-8")
            return RunnerStepResult(
                model_output_text="实现完成",
                next_command_text="",
                done=True,
                meta={"step_status": "passed"},
            )

        if "git 提交" in command_text or "git提交" in command_text:
            subprocess.run(
                ["git", "add", "book-manage/"],
                cwd=self.project_root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )  # noqa: S603
            subprocess.run(
                ["git", "commit", "-m", "feat(book-manage): 产出本轮前端页面。"],
                cwd=self.project_root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )  # noqa: S603
            commit_id_proc = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.project_root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )  # noqa: S603
            commit_msg_proc = subprocess.run(
                ["git", "show", "-s", "--format=%s", "HEAD"],
                cwd=self.project_root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )  # noqa: S603
            commit_id = commit_id_proc.stdout.strip()
            commit_message = commit_msg_proc.stdout.strip()
            return RunnerStepResult(
                model_output_text=f"COMMIT_ID={commit_id}\nCOMMIT_MESSAGE={commit_message}",
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

    def test_default_runtime_root_points_to_project_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runner_factory_map={"mock": _HappyWorkflowRunner},
            )
            self.assertEqual(orchestrator.runtime_root, root / "runtime")

    def test_default_max_rounds_can_finish_record_session_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _HappyWorkflowRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t0",
                task_prompt="实现 book-manage 页面",
                task_type="dev",
                mode="mock",
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "completed")

            events = orchestrator.get_events(run_id)
            commands = [e["command_text"] for e in events if e.get("event_type") == "step_started"]
            self.assertIn("$record-session", commands)

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
                "$check-frontend",
                "$finish-work",
                "git提交",
                "$record-session",
            ]
            self.assertEqual(commands[0], expected[0])
            self.assertEqual(commands[1], expected[1])
            self.assertIn("在目录 book-manage/ 下完成任务：实现 book-manage 页面", commands[2])
            self.assertIn("所有新增或修改文件必须位于 book-manage/", commands[2])
            self.assertEqual(commands[3], expected[2])
            self.assertEqual(commands[4], expected[3])
            self.assertEqual(commands[5], expected[4])
            self.assertEqual(commands[6], expected[5])

    def test_dev_workflow_forces_outputs_under_book_manage_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _HappyWorkflowRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t5",
                task_prompt="实现商城管理后台首页",
                task_type="dev",
                mode="mock",
                max_rounds=12,
                max_rounds_per_window=12,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "completed")

            events = orchestrator.get_events(run_id)
            commands = [e["command_text"] for e in events if e.get("event_type") == "step_started"]
            implementation_command = commands[2]
            self.assertIn("在目录 book-manage/ 下完成任务：实现商城管理后台首页", implementation_command)
            self.assertIn("所有新增或修改文件必须位于 book-manage/", implementation_command)

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

    def test_real_mode_git_step_fails_when_commit_not_executed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"real": _RealNoCommitRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t-real-fail",
                task_prompt="生成加一页面",
                task_type="dev",
                mode="real",
                max_rounds=12,
                max_rounds_per_window=12,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "failed")
            events = orchestrator.get_events(run_id)
            failures = [
                e
                for e in events
                if e.get("event_type") == "step_finished"
                and e.get("meta", {}).get("failure_code") == "FAIL_COMMIT_NOT_EXECUTED"
            ]
            self.assertGreaterEqual(len(failures), 1)

    def test_real_mode_git_step_passes_after_actual_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"real": _RealCommitRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t-real-pass",
                task_prompt="生成加一页面",
                task_type="dev",
                mode="real",
                max_rounds=12,
                max_rounds_per_window=12,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "completed")

            events = orchestrator.get_events(run_id)
            git_step_output = [
                e
                for e in events
                if e.get("event_type") == "model_output" and e.get("meta", {}).get("step_name") == "git提交"
            ]
            self.assertGreaterEqual(len(git_step_output), 1)
            combined_text = "\n".join(str(e.get("model_output_text") or "") for e in git_step_output)
            self.assertIn("COMMIT_ID=", combined_text)


if __name__ == "__main__":
    unittest.main()
