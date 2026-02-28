from __future__ import annotations

import re
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .models import RunnerStepResult
from .runners import MockRunner, RealRunner
from .storage import RuntimeStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _infer_dev_track(task_prompt: str) -> str:
    text = (task_prompt or "").lower()
    frontend_keywords = ("front", "frontend", "页面", "ui", "web", "book-manage", "css", "html", "js")
    backend_keywords = ("backend", "api", "服务", "数据库", "db", "server")
    frontend_hits = sum(1 for kw in frontend_keywords if kw in text)
    backend_hits = sum(1 for kw in backend_keywords if kw in text)
    if backend_hits > frontend_hits:
        return "backend"
    return "frontend"


def _build_scoped_task_prompt(task_prompt: str) -> str:
    scoped_root = "book-manage/"
    normalized = (task_prompt or "").strip()
    if not normalized:
        normalized = "完成当前需求"
    return (
        f"在目录 {scoped_root} 下完成任务：{normalized}\n"
        f"约束：所有新增或修改文件必须位于 {scoped_root}；不要改动其他业务目录。"
    )


def _build_git_commit_command(*, mode: str) -> str:
    if mode != "real":
        return "git提交"

    return (
        "请你直接执行 git 提交，不要只给命令建议。\n"
        "硬性要求：\n"
        "1) 仅提交 book-manage/ 下变更，不要提交其他目录。\n"
        "2) 先执行 git add book-manage/。\n"
        "3) 执行 git commit，message 必须使用：feat(book-manage): 产出本轮前端页面。\n"
        "4) 提交后执行 git rev-parse --short HEAD 与 git show --name-only --pretty=format:%H%n%s -1。\n"
        "5) 在最终输出中给出 COMMIT_ID=<hash> 与 COMMIT_MESSAGE=<message>。\n"
        "6) 如果 book-manage/ 无可提交变更，返回 FAIL_NO_CHANGES。"
    )


def _build_workflow_steps(*, task_type: str, task_prompt: str, mode: str) -> list[Dict[str, str]]:
    if task_type != "dev":
        return []

    track = _infer_dev_track(task_prompt)
    before_step = "$before-backend-dev" if track == "backend" else "$before-frontend-dev"
    check_step = "$check-backend" if track == "backend" else "$check-frontend"

    return [
        {"name": "$start", "command": "$start"},
        {"name": before_step, "command": before_step},
        {"name": "需求实现", "command": _build_scoped_task_prompt(task_prompt)},
        {"name": check_step, "command": check_step},
        {"name": "$finish-work", "command": "$finish-work"},
        {"name": "git提交", "command": _build_git_commit_command(mode=mode)},
        {"name": "$record-session", "command": "$record-session"},
    ]


@dataclass
class _RunContext:
    run_id: str
    task_prompt: str
    task_type: str
    max_rounds: int
    max_rounds_per_window: int
    mode: str
    model_id: str
    reasoning_level: str
    step_delay_seconds: float
    codex_bin: Optional[str]
    snapshot: Dict[str, Any]
    event_seq: int = 0
    interrupted: bool = False
    stop_requested: bool = False
    thread: Optional[threading.Thread] = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    workflow_steps: list[Dict[str, str]] = field(default_factory=list)
    workflow_step_index: int = 0
    workflow_step_attempt: int = 0
    step_max_retry: int = 1
    task_done_signal: bool = False
    last_commit_id: str = ""
    last_commit_message: str = ""
    last_commit_scope: str = ""
    last_model_output: str = ""


class SessionOrchestrator:
    def __init__(
        self,
        *,
        project_root: Optional[Path] = None,
        runtime_root: Optional[Path] = None,
        runner_factory_map: Optional[Dict[str, Callable[..., Any]]] = None,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.runtime_root = runtime_root or (self.project_root / "runtime")
        self.store = RuntimeStore(runtime_root=self.runtime_root)
        self.runner_factory_map = runner_factory_map or {
            "mock": MockRunner,
            "real": RealRunner,
        }
        self._runs: Dict[str, _RunContext] = {}
        self._global_lock = threading.Lock()

    def start_run(
        self,
        *,
        task_id: str,
        task_prompt: str,
        task_type: str = "dev",
        mode: str = "mock",
        model_id: str = "gpt-5.3-codex",
        reasoning_level: str = "medium",
        max_rounds: int = 6,
        max_rounds_per_window: int = 3,
        step_delay_seconds: float = 0.0,
        codex_bin: Optional[str] = None,
        step_max_retry: int = 1,
    ) -> str:
        if max_rounds <= 0:
            raise ValueError("max_rounds 必须大于 0")
        if max_rounds_per_window <= 0:
            raise ValueError("max_rounds_per_window 必须大于 0")
        if step_max_retry < 0:
            raise ValueError("step_max_retry 必须大于等于 0")
        if mode not in self.runner_factory_map:
            raise ValueError(f"不支持的 mode: {mode}")

        workflow_steps = _build_workflow_steps(task_type=task_type, task_prompt=task_prompt, mode=mode)
        if workflow_steps:
            max_rounds = max(max_rounds, len(workflow_steps))
            max_rounds_per_window = max(max_rounds_per_window, len(workflow_steps))

        run_id = f"run-{uuid.uuid4().hex[:12]}"
        window_id = f"{run_id}-window-1"
        snapshot = {
            "run_id": run_id,
            "task_id": task_id,
            "task_type": task_type,
            "status": "running",
            "current_window_index": 1,
            "current_window_id": window_id,
            "current_round_index_in_window": 0,
            "current_global_round_index": 0,
            "current_step_id": "",
            "mode": mode,
            "model_id": model_id,
            "reasoning_level": reasoning_level,
            "current_workflow_step": workflow_steps[0]["name"] if workflow_steps else "",
            "current_workflow_step_index": 0,
            "current_workflow_step_attempt": 0,
            "current_workflow_step_status": "pending" if workflow_steps else "",
            "updated_at": _utc_now(),
        }
        self.store.save_snapshot(snapshot)

        ctx = _RunContext(
            run_id=run_id,
            task_prompt=task_prompt,
            task_type=task_type,
            max_rounds=max_rounds,
            max_rounds_per_window=max_rounds_per_window,
            mode=mode,
            model_id=model_id,
            reasoning_level=reasoning_level,
            step_delay_seconds=step_delay_seconds,
            codex_bin=codex_bin,
            snapshot=snapshot,
            workflow_steps=workflow_steps,
            step_max_retry=step_max_retry,
        )
        worker = threading.Thread(target=self._run_loop, args=(ctx,), daemon=True)
        ctx.thread = worker
        with self._global_lock:
            self._runs[run_id] = ctx
        worker.start()
        return run_id

    def get_snapshot(self, run_id: str) -> Dict[str, Any]:
        return self.store.load_snapshot(run_id)

    def get_events(self, run_id: str, since_seq: int = 0) -> list[Dict[str, Any]]:
        events = self.store.load_events(run_id)
        return [event for event in events if int(event.get("event_seq", 0)) > int(since_seq)]

    def send_operator_message(self, run_id: str, *, operator_id: str, text: str) -> None:
        ctx = self._must_get_context(run_id)
        with ctx.lock:
            if ctx.snapshot["status"] not in {"running", "paused"}:
                raise RuntimeError(f"当前 run 状态不允许插话: {ctx.snapshot['status']}")
            self._append_event(
                ctx,
                event_type="operator_message",
                command_text=text,
                model_output_text="",
                operator_id=operator_id,
                meta={},
            )
            ctx.interrupted = True

    def stop_run(self, run_id: str) -> None:
        ctx = self._must_get_context(run_id)
        with ctx.lock:
            ctx.stop_requested = True

    def export_report(self, run_id: str) -> Path:
        return self.store.export_report(run_id)

    def _must_get_context(self, run_id: str) -> _RunContext:
        with self._global_lock:
            if run_id not in self._runs:
                raise KeyError(f"run 不存在: {run_id}")
            return self._runs[run_id]

    def _run_loop(self, ctx: _RunContext) -> None:
        runner_cls = self.runner_factory_map[ctx.mode]
        runner = runner_cls(
            project_root=self.project_root,
            model_id=ctx.model_id,
            reasoning_level=ctx.reasoning_level,
            step_delay_seconds=ctx.step_delay_seconds,
            codex_bin=ctx.codex_bin,
        )
        current_command = ctx.task_prompt

        try:
            runner.start()
            self._append_event(
                ctx,
                event_type="window_started",
                command_text="",
                model_output_text="",
                operator_id="",
                meta={},
            )
            for _ in range(ctx.max_rounds):
                with ctx.lock:
                    if ctx.stop_requested:
                        self._update_status(ctx, "stopped")
                        break
                    if ctx.interrupted:
                        self._append_event(
                            ctx,
                            event_type="interrupted",
                            command_text=current_command,
                            model_output_text="",
                            operator_id="",
                            meta={},
                        )
                        self._update_status(ctx, "paused")
                        break

                    if not self._uses_fixed_workflow(ctx):
                        if (
                            ctx.snapshot["current_round_index_in_window"] >= ctx.max_rounds_per_window
                            and int(ctx.snapshot["current_global_round_index"]) > 0
                        ):
                            self._append_event(
                                ctx,
                                event_type="window_closed",
                                command_text="",
                                model_output_text="",
                                operator_id="",
                                meta={},
                            )
                            ctx.snapshot["current_window_index"] = int(ctx.snapshot["current_window_index"]) + 1
                            ctx.snapshot["current_window_id"] = (
                                f"{ctx.run_id}-window-{ctx.snapshot['current_window_index']}"
                            )
                            ctx.snapshot["current_round_index_in_window"] = 0
                            self._persist_snapshot(ctx)
                            self._append_event(
                                ctx,
                                event_type="window_started",
                                command_text="",
                                model_output_text="",
                                operator_id="",
                                meta={},
                            )

                    step_name = "task_prompt"
                    if self._uses_fixed_workflow(ctx):
                        step = self._current_workflow_step(ctx)
                        step_name = step["name"]
                        current_command = step["command"]

                    next_global_round = int(ctx.snapshot["current_global_round_index"]) + 1
                    next_round_in_window = int(ctx.snapshot["current_round_index_in_window"]) + 1
                    step_id = f"step-{next_global_round}"
                    step_attempt = ctx.workflow_step_attempt + 1 if self._uses_fixed_workflow(ctx) else 1

                    ctx.snapshot["current_global_round_index"] = next_global_round
                    ctx.snapshot["current_round_index_in_window"] = next_round_in_window
                    ctx.snapshot["current_step_id"] = step_id
                    if self._uses_fixed_workflow(ctx):
                        ctx.snapshot["current_workflow_step"] = step_name
                        ctx.snapshot["current_workflow_step_index"] = ctx.workflow_step_index
                        ctx.snapshot["current_workflow_step_attempt"] = step_attempt
                        ctx.snapshot["current_workflow_step_status"] = "running"
                    self._persist_snapshot(ctx)

                    step_meta = {
                        "step_name": step_name,
                        "step_attempt": step_attempt,
                    }
                    self._append_event(
                        ctx,
                        event_type="step_started",
                        command_text=current_command,
                        model_output_text="",
                        operator_id="",
                        meta=step_meta,
                    )
                    self._append_event(
                        ctx,
                        event_type="model_input",
                        command_text=current_command,
                        model_output_text="",
                        operator_id="",
                        meta=step_meta,
                    )

                step_started_at = datetime.now(timezone.utc)
                git_head_before = ""
                if self._uses_fixed_workflow(ctx) and step_name == "git提交":
                    git_head_before = self._git_head_commit()
                prechecked = self._precheck_step(ctx=ctx, step_name=step_name, command_text=current_command)
                if prechecked is None:
                    result = runner.run_step(
                        command_text=current_command,
                        global_round_index=next_global_round,
                        round_index_in_window=next_round_in_window,
                        window_index=int(ctx.snapshot["current_window_index"]),
                        step_id=step_id,
                    )
                else:
                    result = prechecked

                if self._uses_fixed_workflow(ctx) and step_name == "git提交":
                    result = self._postcheck_git_step(ctx=ctx, result=result, head_before=git_head_before)

                duration_ms = int((datetime.now(timezone.utc) - step_started_at).total_seconds() * 1000)
                step_status, step_meta = self._resolve_step_result(step_name=step_name, result=result)

                with ctx.lock:
                    ctx.last_model_output = result.model_output_text
                    model_meta = dict(step_meta)
                    model_meta.update(result.meta or {})
                    self._append_event(
                        ctx,
                        event_type="model_output",
                        command_text=current_command,
                        model_output_text=result.model_output_text,
                        operator_id="",
                        duration_ms=duration_ms,
                        meta=model_meta,
                    )
                    self._append_event(
                        ctx,
                        event_type="step_finished",
                        command_text=current_command,
                        model_output_text=result.model_output_text,
                        operator_id="",
                        duration_ms=duration_ms,
                        meta=step_meta,
                    )

                    if self._uses_fixed_workflow(ctx):
                        ctx.snapshot["current_workflow_step_status"] = step_status
                        self._persist_snapshot(ctx)

                    if ctx.interrupted:
                        self._append_event(
                            ctx,
                            event_type="interrupted",
                            command_text=current_command,
                            model_output_text=result.model_output_text,
                            operator_id="",
                            meta={"reason": "operator_message"},
                        )
                        self._update_status(ctx, "paused")
                        break

                    if step_status == "passed":
                        if step_name == "git提交":
                            self._capture_commit_evidence(ctx, result)
                        if result.done:
                            ctx.task_done_signal = True

                        if self._uses_fixed_workflow(ctx):
                            self._advance_workflow_step(ctx)
                            if self._workflow_finished(ctx):
                                if ctx.task_done_signal:
                                    self._append_event(
                                        ctx,
                                        event_type="window_closed",
                                        command_text="",
                                        model_output_text="",
                                        operator_id="",
                                        meta={"reason": "completed"},
                                    )
                                    self._update_status(ctx, "completed")
                                    break
                                switched = self._start_new_window(ctx, reason="workflow_completed")
                                if not switched:
                                    self._update_status(ctx, "failed")
                                    break
                                continue
                            continue

                        if result.done:
                            self._append_event(
                                ctx,
                                event_type="window_closed",
                                command_text="",
                                model_output_text="",
                                operator_id="",
                                meta={"reason": "completed"},
                            )
                            self._update_status(ctx, "completed")
                            break
                        current_command = result.next_command_text or current_command
                    else:
                        if self._uses_fixed_workflow(ctx) and ctx.workflow_step_attempt < ctx.step_max_retry:
                            ctx.workflow_step_attempt += 1
                            ctx.snapshot["current_workflow_step_attempt"] = ctx.workflow_step_attempt + 1
                            ctx.snapshot["current_workflow_step_status"] = "retrying"
                            self._persist_snapshot(ctx)
                            self._append_event(
                                ctx,
                                event_type="step_retrying",
                                command_text=current_command,
                                model_output_text=result.model_output_text,
                                operator_id="",
                                meta={
                                    "step_name": step_name,
                                    "step_attempt": ctx.workflow_step_attempt + 1,
                                    "failure_code": step_meta.get("failure_code", ""),
                                },
                            )
                            continue

                        if self._uses_fixed_workflow(ctx):
                            self._append_event(
                                ctx,
                                event_type="policy_decision",
                                command_text=current_command,
                                model_output_text="",
                                operator_id="",
                                meta={
                                    "action": "start_new_window",
                                    "reason": "retry_exhausted",
                                    "step_name": step_name,
                                },
                            )
                            switched = self._start_new_window(ctx, reason="retry_exhausted")
                            if not switched:
                                self._update_status(ctx, "failed")
                                break
                            continue

                        self._update_status(ctx, "failed")
                        break
            else:
                with ctx.lock:
                    self._append_event(
                        ctx,
                        event_type="window_closed",
                        command_text="",
                        model_output_text="",
                        operator_id="",
                        meta={"reason": "max_rounds_reached"},
                    )
                    self._update_status(ctx, "completed")
        except Exception as exc:  # noqa: BLE001
            with ctx.lock:
                self._append_event(
                    ctx,
                    event_type="error",
                    command_text=current_command,
                    model_output_text="",
                    operator_id="",
                    meta={"error": str(exc)},
                )
                self._update_status(ctx, "failed")
        finally:
            runner.stop()
            self.store.save_snapshot(ctx.snapshot)

    def _uses_fixed_workflow(self, ctx: _RunContext) -> bool:
        return bool(ctx.workflow_steps)

    def _current_workflow_step(self, ctx: _RunContext) -> Dict[str, str]:
        return ctx.workflow_steps[ctx.workflow_step_index]

    def _advance_workflow_step(self, ctx: _RunContext) -> None:
        ctx.workflow_step_index += 1
        ctx.workflow_step_attempt = 0
        if ctx.workflow_step_index < len(ctx.workflow_steps):
            ctx.snapshot["current_workflow_step"] = ctx.workflow_steps[ctx.workflow_step_index]["name"]
            ctx.snapshot["current_workflow_step_index"] = ctx.workflow_step_index
            ctx.snapshot["current_workflow_step_attempt"] = 0
            ctx.snapshot["current_workflow_step_status"] = "pending"
            self._persist_snapshot(ctx)

    def _workflow_finished(self, ctx: _RunContext) -> bool:
        return ctx.workflow_step_index >= len(ctx.workflow_steps)

    def _start_new_window(self, ctx: _RunContext, *, reason: str) -> bool:
        handoff = self._build_handoff(ctx)
        missing = self._validate_handoff(ctx, handoff)
        if missing:
            self._append_event(
                ctx,
                event_type="handoff_blocked",
                command_text="",
                model_output_text="",
                operator_id="",
                meta={
                    "reason": reason,
                    "missing_fields": missing,
                },
            )
            return False

        self._append_event(
            ctx,
            event_type="handoff_validated",
            command_text="",
            model_output_text="",
            operator_id="",
            meta={"handoff": handoff},
        )
        self._append_event(
            ctx,
            event_type="policy_decision",
            command_text="",
            model_output_text="",
            operator_id="",
            meta={"action": "start_new_window", "reason": reason},
        )
        self._append_event(
            ctx,
            event_type="window_closed",
            command_text="",
            model_output_text="",
            operator_id="",
            meta={"reason": reason},
        )

        ctx.snapshot["current_window_index"] = int(ctx.snapshot["current_window_index"]) + 1
        ctx.snapshot["current_window_id"] = f"{ctx.run_id}-window-{ctx.snapshot['current_window_index']}"
        ctx.snapshot["current_round_index_in_window"] = 0
        ctx.snapshot["current_step_id"] = ""
        ctx.workflow_step_index = 0
        ctx.workflow_step_attempt = 0
        if ctx.workflow_steps:
            ctx.snapshot["current_workflow_step"] = ctx.workflow_steps[0]["name"]
            ctx.snapshot["current_workflow_step_index"] = 0
            ctx.snapshot["current_workflow_step_attempt"] = 0
            ctx.snapshot["current_workflow_step_status"] = "pending"
        self._persist_snapshot(ctx)
        self._append_event(
            ctx,
            event_type="window_started",
            command_text="",
            model_output_text="",
            operator_id="",
            meta={"handoff": handoff},
        )
        return True

    def _build_handoff(self, ctx: _RunContext) -> Dict[str, Any]:
        completed = [step["name"] for step in ctx.workflow_steps]
        return {
            "task_id": ctx.snapshot.get("task_id", ""),
            "task_goal": ctx.task_prompt,
            "current_stage": "window_completed",
            "completed_steps": completed,
            "pending_steps": [step["name"] for step in ctx.workflow_steps],
            "last_round_result": ctx.last_model_output,
            "last_commit_id": ctx.last_commit_id,
            "last_commit_message": ctx.last_commit_message,
            "last_commit_scope": ctx.last_commit_scope,
            "known_issues": [],
            "next_actions": [ctx.task_prompt],
        }

    def _validate_handoff(self, ctx: _RunContext, handoff: Dict[str, Any]) -> list[str]:
        required = ["task_goal"]
        if ctx.task_type == "dev":
            required.extend(["last_commit_id", "last_commit_message"])
        return [field for field in required if not str(handoff.get(field, "")).strip()]

    def _precheck_step(
        self,
        *,
        ctx: _RunContext,
        step_name: str,
        command_text: str,
    ) -> Optional[RunnerStepResult]:
        if step_name != "git提交":
            return None

        has_changes = self._detect_git_changes()
        if has_changes is False and ctx.task_type == "dev":
            return RunnerStepResult(
                model_output_text="dev 场景禁止空提交：工作区无代码变更。",
                next_command_text=command_text,
                done=False,
                meta={
                    "step_status": "failed",
                    "failure_code": "FAIL_NO_CHANGES",
                    "has_code_changes": False,
                },
            )
        if has_changes is False and ctx.task_type == "planning":
            return RunnerStepResult(
                model_output_text="planning 场景无代码变更：允许空提交。",
                next_command_text=command_text,
                done=False,
                meta={
                    "step_status": "passed",
                    "allow_empty_commit": True,
                    "has_code_changes": False,
                },
            )
        return None

    def _resolve_step_result(self, *, step_name: str, result: RunnerStepResult) -> tuple[str, Dict[str, Any]]:
        output_text = str(result.model_output_text or "")
        meta = dict(result.meta or {})
        raw_status = str(meta.get("step_status") or "").lower().strip()
        if raw_status not in {"passed", "failed"}:
            if "FAIL_" in output_text:
                raw_status = "failed"
            else:
                raw_status = "passed"

        step_meta = {
            "step_name": step_name,
            "step_status": raw_status,
            "failure_code": str(meta.get("failure_code") or ""),
        }
        if "has_code_changes" in meta:
            step_meta["has_code_changes"] = meta.get("has_code_changes")
        if "allow_empty_commit" in meta:
            step_meta["allow_empty_commit"] = meta.get("allow_empty_commit")
        return raw_status, step_meta

    def _capture_commit_evidence(self, ctx: _RunContext, result: RunnerStepResult) -> None:
        meta = result.meta or {}
        output_text = str(result.model_output_text or "")

        commit_id = str(meta.get("commit_id") or "").strip()
        commit_message = str(meta.get("commit_message") or "").strip()
        commit_scope = str(meta.get("commit_scope") or "").strip()

        if not commit_id:
            commit_id_match = re.search(r"COMMIT_ID\s*=\s*([0-9a-fA-F]{7,40})", output_text)
            if commit_id_match:
                commit_id = commit_id_match.group(1)

        if not commit_message:
            commit_msg_match = re.search(r"COMMIT_MESSAGE\s*=\s*(.+)", output_text)
            if commit_msg_match:
                commit_message = commit_msg_match.group(1).strip()

        ctx.last_commit_id = commit_id
        ctx.last_commit_message = commit_message
        ctx.last_commit_scope = commit_scope

    def _detect_git_changes(self) -> Optional[bool]:
        cmd = ["git", "status", "--porcelain"]
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=self.project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if proc.returncode != 0:
            return None
        ignored_prefixes = (
            "runtime/",
            "src/runtime/",
            "session-orchestrator/runtime/",
        )
        for raw_line in proc.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if len(line) < 4:
                continue
            path_part = line[3:].strip()
            if path_part.startswith('"') and path_part.endswith('"'):
                path_part = path_part[1:-1]
            normalized = path_part.replace("\\", "/")
            if any(normalized.startswith(prefix) for prefix in ignored_prefixes):
                continue
            return True
        return False

    def _git_head_commit(self) -> str:
        cmd = ["git", "rev-parse", "HEAD"]
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=self.project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if proc.returncode != 0:
            return ""
        return str(proc.stdout or "").strip()

    def _git_head_subject(self) -> str:
        cmd = ["git", "show", "-s", "--format=%s", "HEAD"]
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=self.project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if proc.returncode != 0:
            return ""
        return str(proc.stdout or "").strip()

    def _postcheck_git_step(
        self,
        *,
        ctx: _RunContext,
        result: RunnerStepResult,
        head_before: str,
    ) -> RunnerStepResult:
        if ctx.mode != "real":
            return result

        output_text = str(result.model_output_text or "")
        if "FAIL_NO_CHANGES" in output_text:
            return RunnerStepResult(
                model_output_text=output_text,
                next_command_text=result.next_command_text,
                done=result.done,
                meta={"step_status": "failed", "failure_code": "FAIL_NO_CHANGES"},
            )

        head_after = self._git_head_commit()
        if not head_after or (head_before and head_after == head_before):
            return RunnerStepResult(
                model_output_text=(
                    f"{output_text}\n\n"
                    "FAIL_COMMIT_NOT_EXECUTED: git提交步骤未检测到新的提交记录，请实际执行 git commit。"
                ),
                next_command_text=result.next_command_text,
                done=result.done,
                meta={"step_status": "failed", "failure_code": "FAIL_COMMIT_NOT_EXECUTED"},
            )

        enriched_meta = dict(result.meta or {})
        enriched_meta["commit_id"] = enriched_meta.get("commit_id") or head_after
        enriched_meta["commit_message"] = enriched_meta.get("commit_message") or self._git_head_subject()
        enriched_meta["step_status"] = "passed"
        return RunnerStepResult(
            model_output_text=output_text,
            next_command_text=result.next_command_text,
            done=result.done,
            meta=enriched_meta,
        )

    def _update_status(self, ctx: _RunContext, status: str) -> None:
        ctx.snapshot["status"] = status
        self._persist_snapshot(ctx)

    def _persist_snapshot(self, ctx: _RunContext) -> None:
        ctx.snapshot["updated_at"] = _utc_now()
        self.store.save_snapshot(ctx.snapshot)

    def _append_event(
        self,
        ctx: _RunContext,
        *,
        event_type: str,
        command_text: str,
        model_output_text: str,
        operator_id: str,
        meta: Dict[str, Any],
        duration_ms: Optional[int] = None,
    ) -> None:
        ctx.event_seq += 1
        event = {
            "event_seq": ctx.event_seq,
            "event_id": f"{ctx.run_id}-event-{ctx.event_seq:06d}",
            "run_id": ctx.run_id,
            "window_index": int(ctx.snapshot["current_window_index"]),
            "window_id": ctx.snapshot["current_window_id"],
            "round_index_in_window": int(ctx.snapshot["current_round_index_in_window"]),
            "global_round_index": int(ctx.snapshot["current_global_round_index"]),
            "step_id": ctx.snapshot["current_step_id"],
            "event_type": event_type,
            "command_text": command_text,
            "model_output_text": model_output_text,
            "operator_id": operator_id,
            "timestamp": _utc_now(),
            "duration_ms": duration_ms,
            "meta": meta,
        }
        self.store.append_event(event)
