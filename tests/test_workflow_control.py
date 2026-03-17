from __future__ import annotations

import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from orchestrator.models import RunnerStepResult
from orchestrator.service import SessionOrchestrator


def _extract_scope_path(command_text: str, default_scope: str = "book-manage/") -> str:
    match = re.search(r"在目录\s+(.+?)\s+下完成任务", command_text or "")
    if not match:
        return default_scope
    return match.group(1).strip() or default_scope


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


class _ScopedWorkflowRunner(_BaseFakeRunner):
    def run_step(
        self,
        *,
        command_text: str,
        global_round_index: int,
        round_index_in_window: int,
        window_index: int,
        step_id: str,
    ) -> RunnerStepResult:
        if "下完成任务" in command_text:
            scope_path = _extract_scope_path(command_text, "apps/web/")
            scope_dir = self.project_root / scope_path.strip("/")
            scope_dir.mkdir(parents=True, exist_ok=True)
            (scope_dir / "index.html").write_text("<!doctype html><title>scoped</title>", encoding="utf-8")
            return RunnerStepResult(
                model_output_text="作用域实现完成",
                next_command_text="",
                done=True,
                meta={"step_status": "passed"},
            )
        if command_text == "git提交":
            return RunnerStepResult(
                model_output_text="git 提交通过",
                next_command_text="",
                done=False,
                meta={
                    "step_status": "passed",
                    "commit_id": "scope123",
                    "commit_message": "feat(scope): scoped output",
                    "commit_scope": "apps/web/",
                },
            )
        return RunnerStepResult(
            model_output_text=f"{command_text} 已完成",
            next_command_text="",
            done=False,
            meta={"step_status": "passed"},
        )


class _OutOfScopeChangeRunner(_BaseFakeRunner):
    def run_step(
        self,
        *,
        command_text: str,
        global_round_index: int,
        round_index_in_window: int,
        window_index: int,
        step_id: str,
    ) -> RunnerStepResult:
        if "下完成任务" in command_text:
            target = self.project_root / "outside" / "index.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("<!doctype html><title>outside</title>", encoding="utf-8")
            return RunnerStepResult(
                model_output_text="仅在作用域外写入文件",
                next_command_text="",
                done=True,
                meta={"step_status": "passed"},
            )
        return RunnerStepResult(
            model_output_text=f"{command_text} 已处理",
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


class _RealNoCommitMentionsFailNoChangesRunner(_BaseFakeRunner):
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
                model_output_text="不是 FAIL_NO_CHANGES，但我没有真正执行 commit。",
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


class _WorkItemWorkflowRunner(_BaseFakeRunner):
    def run_step(
        self,
        *,
        command_text: str,
        global_round_index: int,
        round_index_in_window: int,
        window_index: int,
        step_id: str,
    ) -> RunnerStepResult:
        if "下完成任务" in command_text or "内完成任务" in command_text:
            scope_path = _extract_scope_path(command_text, "book-manage/")
            scope_dir = self.project_root / scope_path.strip("/")
            scope_dir.mkdir(parents=True, exist_ok=True)
            (scope_dir / "work-item.txt").write_text(f"round={global_round_index}\n", encoding="utf-8")
            return RunnerStepResult(
                model_output_text="实现完成",
                next_command_text="",
                done=True,
                meta={"step_status": "passed"},
            )

        if command_text == "git提交":
            return RunnerStepResult(
                model_output_text="git 提交通过",
                next_command_text="",
                done=False,
                meta={
                    "step_status": "passed",
                    "commit_id": f"wi-{global_round_index:04d}",
                    "commit_message": "feat: work item commit",
                    "commit_scope": "book-manage/",
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

    def _wait_until_status_not(self, orchestrator: SessionOrchestrator, run_id: str, status: str, timeout: float = 8.0) -> dict:
        deadline = time.time() + timeout
        snapshot = {}
        while time.time() < deadline:
            snapshot = orchestrator.get_snapshot(run_id)
            if snapshot.get("status") != status:
                return snapshot
            time.sleep(0.05)
        self.fail(f"run 状态未在超时内离开 {status}: {run_id}, last={snapshot}")

    def _wait_until_status_in(
        self,
        orchestrator: SessionOrchestrator,
        run_id: str,
        statuses: set[str],
        timeout: float = 8.0,
    ) -> dict:
        deadline = time.time() + timeout
        snapshot = {}
        while time.time() < deadline:
            snapshot = orchestrator.get_snapshot(run_id)
            if snapshot.get("status") in statuses:
                return snapshot
            time.sleep(0.05)
        self.fail(f"run 状态未在超时内达到目标集合 {statuses}: {run_id}, last={snapshot}")

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

    def test_dev_workflow_uses_path_wording_when_scope_is_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _NoChangeRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t-file-scope-prompt",
                task_prompt="优化输入框样式",
                task_type="dev",
                mode="mock",
                max_rounds=12,
                max_rounds_per_window=12,
                git_scope_path="app/(tabs)/index.tsx",
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertIn(snapshot.get("status"), {"failed", "completed"})

            events = orchestrator.get_events(run_id)
            commands = [e["command_text"] for e in events if e.get("event_type") == "step_started"]
            implementation_command = commands[2]
            self.assertIn("在路径 app/(tabs)/index.tsx 内完成任务：优化输入框样式", implementation_command)
            self.assertIn("所有新增或修改文件必须位于 app/(tabs)/index.tsx", implementation_command)

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

    def test_can_run_against_external_workspace_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestrator_root = root / "orchestrator"
            external_root = root / "external-app"
            orchestrator_root.mkdir(parents=True, exist_ok=True)
            external_root.mkdir(parents=True, exist_ok=True)
            self._init_git_repo(external_root)

            orchestrator = SessionOrchestrator(
                project_root=orchestrator_root,
                runtime_root=orchestrator_root / "runtime",
                runner_factory_map={"mock": _ScopedWorkflowRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t-external",
                task_prompt="实现外部项目页面",
                task_type="dev",
                mode="mock",
                max_rounds=12,
                max_rounds_per_window=12,
                workspace_project_root=str(external_root),
                git_scope_path="apps/web/",
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "completed")
            self.assertEqual(snapshot.get("workspace_project_root"), str(external_root.resolve()))
            self.assertEqual(snapshot.get("git_scope_path"), "apps/web/")
            self.assertTrue((external_root / "apps" / "web" / "index.html").exists())

            events = orchestrator.get_events(run_id)
            commands = [e["command_text"] for e in events if e.get("event_type") == "step_started"]
            self.assertIn("在目录 apps/web/ 下完成任务：实现外部项目页面", commands[2])

    def test_git_change_detection_is_limited_to_scope_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _OutOfScopeChangeRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t-scope-fail",
                task_prompt="实现但只写作用域外文件",
                task_type="dev",
                mode="mock",
                max_rounds=12,
                max_rounds_per_window=12,
                git_scope_path="apps/web/",
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertIn(snapshot.get("status"), {"failed", "completed"})

            events = orchestrator.get_events(run_id)
            scoped_fail = [
                e
                for e in events
                if e.get("event_type") == "step_finished"
                and e.get("meta", {}).get("failure_code") == "FAIL_NO_CHANGES"
            ]
            self.assertGreaterEqual(len(scoped_fail), 1)

    def test_start_run_rejects_non_git_workspace_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_root = root / "repo"
            not_repo = root / "not-repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            not_repo.mkdir(parents=True, exist_ok=True)
            self._init_git_repo(repo_root)
            orchestrator = SessionOrchestrator(
                project_root=repo_root,
                runtime_root=repo_root / "runtime",
                runner_factory_map={"mock": _HappyWorkflowRunner},
            )
            with self.assertRaises(ValueError):
                orchestrator.start_run(
                    task_id="t-invalid-root",
                    task_prompt="实现页面",
                    task_type="dev",
                    mode="mock",
                    workspace_project_root=str(not_repo),
                )

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

    def test_real_mode_git_step_does_not_misclassify_fail_no_changes_from_sentence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"real": _RealNoCommitMentionsFailNoChangesRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t-real-fail-nochanges-sentence",
                task_prompt="生成加一页面",
                task_type="dev",
                mode="real",
                max_rounds=12,
                max_rounds_per_window=12,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "failed")
            events = orchestrator.get_events(run_id)
            commit_not_executed_failures = [
                e
                for e in events
                if e.get("event_type") == "step_finished"
                and e.get("meta", {}).get("failure_code") == "FAIL_COMMIT_NOT_EXECUTED"
            ]
            self.assertGreaterEqual(len(commit_not_executed_failures), 1)

    def test_snapshot_has_default_dev_unfinished_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _HappyWorkflowRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t-threshold-default",
                task_prompt="实现 book-manage 页面",
                task_type="dev",
                mode="mock",
                max_rounds=12,
                max_rounds_per_window=12,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "completed")
            self.assertEqual(int(snapshot.get("dev_unfinished_threshold_n", 0)), 1)

    def test_each_round_records_policy_basis_result_and_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _HappyWorkflowRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t-policy-each-round",
                task_prompt="实现 book-manage 页面",
                task_type="dev",
                mode="mock",
                max_rounds=12,
                max_rounds_per_window=12,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "completed")

            events = orchestrator.get_events(run_id)
            step_finished = [e for e in events if e.get("event_type") == "step_finished"]
            policy_events = [e for e in events if e.get("event_type") == "policy_decision"]
            self.assertGreaterEqual(len(policy_events), len(step_finished))
            self.assertGreater(len(policy_events), 0)
            for event in policy_events:
                meta = dict(event.get("meta", {}))
                self.assertTrue(str(meta.get("decision_basis", "")).strip())
                self.assertTrue(str(meta.get("decision_result", "")).strip())
                self.assertTrue(str(meta.get("action", "")).strip())

    def test_start_new_window_policy_exposes_new_thread_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _HandoffReadyRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t-new-window-semantics",
                task_prompt="实现并继续下一窗口",
                task_type="dev",
                mode="mock",
                max_rounds=8,
                max_rounds_per_window=8,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "completed")

            events = orchestrator.get_events(run_id)
            decisions = [
                e
                for e in events
                if e.get("event_type") == "policy_decision"
                and e.get("meta", {}).get("action") == "start_new_window"
            ]
            self.assertGreaterEqual(len(decisions), 1)
            latest_meta = dict(decisions[-1].get("meta", {}))
            self.assertEqual(latest_meta.get("window_switch_command"), "/new")
            self.assertEqual(latest_meta.get("window_switch_semantics"), "new_thread_same_process")

    def test_git_commit_step_records_prompt_template_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _HappyWorkflowRunner},
            )
            run_id = orchestrator.start_run(
                task_id="t-git-template-source",
                task_prompt="实现 book-manage 页面",
                task_type="dev",
                mode="mock",
                max_rounds=12,
                max_rounds_per_window=12,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "completed")

            events = orchestrator.get_events(run_id)
            git_step_started = [
                e
                for e in events
                if e.get("event_type") == "step_started"
                and e.get("meta", {}).get("step_name") == "git提交"
            ]
            self.assertGreaterEqual(len(git_step_started), 1)
            meta = dict(git_step_started[0].get("meta", {}))
            self.assertEqual(meta.get("prompt_template_key"), "git_commit")
            self.assertTrue(str(meta.get("prompt_template_source", "")).strip())

    def test_work_items_snapshot_and_human_review_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _WorkItemWorkflowRunner},
            )
            run_id = orchestrator.start_run(
                task_id="wi-0",
                task_prompt="实现 book-manage 页面并补齐测试",
                task_type="dev",
                workflow_mode="work_items",
                mode="mock",
                max_rounds=80,
                max_rounds_per_window=80,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "paused")
            self.assertEqual(snapshot.get("workflow_mode"), "work_items")
            self.assertEqual(snapshot.get("pause_reason"), "human_review")

            work_payload = orchestrator.get_work_items(run_id)
            self.assertGreaterEqual(len(work_payload.get("work_items") or []), 1)
            self.assertEqual(work_payload.get("current_work_item_id"), snapshot.get("current_work_item_id"))

            events = orchestrator.get_events(run_id)
            commands = [e["command_text"] for e in events if e.get("event_type") == "step_started"]
            self.assertIn("command_review", commands)
            self.assertIn("human_review", commands)
            self.assertNotIn("git提交", commands)

            orchestrator.submit_human_review(
                run_id,
                work_item_id=str(snapshot.get("current_work_item_id") or ""),
                decision="approve",
                note="ok",
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "completed")

            events = orchestrator.get_events(run_id)
            commands = [e["command_text"] for e in events if e.get("event_type") == "step_started"]
            self.assertIn("git提交", commands)
            self.assertLess(commands.index("human_review"), commands.index("git提交"))

    def test_work_items_implementation_prompt_keeps_goal_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _WorkItemWorkflowRunner},
            )
            task_prompt = "\n".join(
                [
                    "实现 book-manage 页面",
                    "- 要求：显示列表",
                    "- 要求：补齐测试",
                ]
            )
            run_id = orchestrator.start_run(
                task_id="wi-prompt-goal",
                task_prompt=task_prompt,
                task_type="dev",
                workflow_mode="work_items",
                mode="mock",
                max_rounds=80,
                max_rounds_per_window=80,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "paused")
            self.assertEqual(snapshot.get("pause_reason"), "human_review")

            events = orchestrator.get_events(run_id)
            impl_steps = [
                e
                for e in events
                if e.get("event_type") == "step_started"
                and e.get("meta", {}).get("step_name") == "需求实现"
            ]
            self.assertGreaterEqual(len(impl_steps), 1)
            impl_prompt = str(impl_steps[0].get("command_text") or "")
            self.assertIn("要求：显示列表", impl_prompt)
            self.assertIn("要求：补齐测试", impl_prompt)
            self.assertNotIn("仅围绕当前 WorkItem 的验收点推进", impl_prompt)

    def test_human_review_reject_creates_fix_work_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _WorkItemWorkflowRunner},
            )
            run_id = orchestrator.start_run(
                task_id="wi-reject",
                task_prompt="实现 book-manage 页面并补齐测试",
                task_type="dev",
                workflow_mode="work_items",
                mode="mock",
                max_rounds=160,
                max_rounds_per_window=160,
            )
            snapshot = self._wait_status(orchestrator, run_id)
            self.assertEqual(snapshot.get("status"), "paused")
            self.assertEqual(snapshot.get("pause_reason"), "human_review")
            first_id = str(snapshot.get("current_work_item_id") or "")

            orchestrator.submit_human_review(
                run_id,
                work_item_id=first_id,
                decision="reject",
                note="needs fix",
            )
            snapshot = self._wait_status(orchestrator, run_id, timeout=10.0)
            self.assertEqual(snapshot.get("status"), "paused")
            self.assertEqual(snapshot.get("pause_reason"), "human_review")

            work_payload = orchestrator.get_work_items(run_id)
            items = work_payload.get("work_items") or []
            self.assertGreaterEqual(len(items), 2)
            self.assertNotEqual(work_payload.get("current_work_item_id"), first_id)
            self.assertEqual(str(items[0].get("status") or ""), "failed")
            self.assertEqual(int(items[0].get("failure_streak") or 0), 1)

    def test_work_item_circuit_breaker_trips_after_repeated_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._init_git_repo(root)
            orchestrator = SessionOrchestrator(
                project_root=root,
                runtime_root=root / "runtime",
                runner_factory_map={"mock": _WorkItemWorkflowRunner},
            )
            run_id = orchestrator.start_run(
                task_id="wi-cb",
                task_prompt="实现 book-manage 页面并补齐测试",
                task_type="dev",
                workflow_mode="work_items",
                mode="mock",
                max_rounds=300,
                max_rounds_per_window=300,
            )

            for idx in range(4):
                snapshot = self._wait_status(orchestrator, run_id, timeout=12.0)
                self.assertEqual(snapshot.get("status"), "paused")
                pause_reason = str(snapshot.get("pause_reason") or "")
                if pause_reason == "circuit_breaker":
                    break
                self.assertEqual(pause_reason, "human_review")
                current_id = str(snapshot.get("current_work_item_id") or "")
                orchestrator.submit_human_review(
                    run_id,
                    work_item_id=current_id,
                    decision="reject",
                    note=f"reject-{idx}",
                )

            snapshot = orchestrator.get_snapshot(run_id)
            self.assertEqual(snapshot.get("status"), "paused")
            self.assertEqual(snapshot.get("pause_reason"), "circuit_breaker")


if __name__ == "__main__":
    unittest.main()
