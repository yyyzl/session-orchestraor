from __future__ import annotations

import json
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

_WINDOW_SWITCH_COMMAND = "/new"
_WINDOW_SWITCH_SEMANTICS = "new_thread_same_process"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_scope_path(raw: str) -> str:
    text = (raw or "").strip().replace("\\", "/")
    if not text or text in {".", "./"}:
        return ""
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise ValueError("git_scope_path 必须是仓库内相对路径")

    keep_trailing = text.endswith("/")
    parts: list[str] = []
    for part in text.split("/"):
        segment = part.strip()
        if not segment or segment == ".":
            continue
        if segment == "..":
            raise ValueError("git_scope_path 不能包含 ..")
        parts.append(segment)
    if not parts:
        return ""

    normalized = "/".join(parts)
    if keep_trailing:
        normalized += "/"
    return normalized


def _scope_label(scope_path: str) -> str:
    return scope_path or "仓库根目录"


def _scope_base(scope_path: str) -> str:
    return scope_path.rstrip("/")


def _path_in_scope(path: str, scope_path: str) -> bool:
    if not scope_path:
        return True
    base = _scope_base(scope_path)
    if not base:
        return True
    return path == base or path.startswith(f"{base}/")


class _TemplateMap(dict):
    def __missing__(self, key: str) -> str:  # noqa: D401
        return ""


def _render_template(template: str, variables: Dict[str, str]) -> str:
    if not template:
        return ""
    return template.format_map(_TemplateMap(variables))


def _deep_merge_dict(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_prompt_template(
    *,
    prompt_config: Dict[str, Any],
    task_type: str,
    prompt_key: str,
    default_template: str,
) -> tuple[str, str]:
    overrides = prompt_config.get("prompt_overrides", {})
    task_overrides = overrides.get(task_type, {}) if isinstance(overrides, dict) else {}
    if isinstance(task_overrides, dict) and prompt_key in task_overrides:
        candidate = str(task_overrides.get(prompt_key) or "")
        if candidate:
            return candidate, f"prompt_overrides.{task_type}.{prompt_key}"

    prompts = prompt_config.get("prompts", {})
    if isinstance(prompts, dict) and prompt_key in prompts:
        candidate = str(prompts.get(prompt_key) or "")
        if candidate:
            return candidate, f"prompts.{prompt_key}"

    return str(default_template), f"defaults.{prompt_key}"


_DEFAULT_PROMPT_CONFIG: Dict[str, Any] = {
    "defaults": {
        "git_scope_path": "book-manage/",
    },
    "prompts": {
        "implementation": (
            "在目录 {scope_path} 下完成任务：{task_prompt}\n"
            "约束：所有新增或修改文件必须位于 {scope_path}；不要改动其他业务目录。"
        ),
        "git_commit": (
            "请你直接执行 git 提交，不要只给命令建议。\n"
            "硬性要求：\n"
            "1) 仅提交 {scope_path} 下变更，不要提交其他目录。\n"
            "2) 先执行 git add {git_add_target}。\n"
            "3) 执行 git commit，message 必须使用：{commit_message}。\n"
            "4) 提交后执行 git rev-parse --short HEAD 与 git show --name-only --pretty=format:%H%n%s -1。\n"
            "5) 在最终输出中给出 COMMIT_ID=<hash> 与 COMMIT_MESSAGE=<message>。\n"
            "6) 如果 {scope_path} 无可提交变更，返回 FAIL_NO_CHANGES。"
        ),
    },
    "prompt_overrides": {
        "dev": {
            "git_commit": (
                "请你直接执行 git 提交，不要只给命令建议。\n"
                "硬性要求：\n"
                "1) 仅提交 {scope_path} 下变更，不要提交其他目录。\n"
                "2) 先执行 git add {git_add_target}。\n"
                "3) 执行 git commit，message 必须使用：{commit_message}。\n"
                "4) 提交后执行 git rev-parse --short HEAD 与 git show --name-only --pretty=format:%H%n%s -1。\n"
                "5) 在最终输出中给出 COMMIT_ID=<hash> 与 COMMIT_MESSAGE=<message>。\n"
                "6) 如果 {scope_path} 无可提交变更，返回 FAIL_NO_CHANGES。"
            )
        },
        "planning": {
            "git_commit": (
                "请你直接执行 git 提交，不要只给命令建议。\n"
                "规则：\n"
                "1) 优先提交 {scope_path} 下变更。\n"
                "2) 先执行 git add {git_add_target}。\n"
                "3) 若无变更必须执行空提交：git commit --allow-empty -m \"{commit_message}\"。\n"
                "4) 在最终输出中给出 COMMIT_ID=<hash> 与 COMMIT_MESSAGE=<message>。"
            )
        },
    },
    "commit_message_by_task_type": {
        "dev": "feat(book-manage): 产出本轮前端页面。",
        "planning": "chore(planning): 记录本轮规划会话。",
        "default": "chore(orchestrator): 完成本轮会话编排步骤。",
    },
}


def _load_prompt_config(path: Optional[Path]) -> Dict[str, Any]:
    config = dict(_DEFAULT_PROMPT_CONFIG)
    if path is None or not path.exists():
        return config

    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"提示词配置文件格式非法: {path}")
    return _deep_merge_dict(config, parsed)


def _infer_dev_track(task_prompt: str) -> str:
    text = (task_prompt or "").lower()
    frontend_keywords = ("front", "frontend", "页面", "ui", "web", "book-manage", "css", "html", "js")
    backend_keywords = ("backend", "api", "服务", "数据库", "db", "server")
    frontend_hits = sum(1 for kw in frontend_keywords if kw in text)
    backend_hits = sum(1 for kw in backend_keywords if kw in text)
    if backend_hits > frontend_hits:
        return "backend"
    return "frontend"


def _build_scoped_task_prompt(
    *,
    task_prompt: str,
    scope_path: str,
    task_type: str,
    prompt_config: Dict[str, Any],
    template_variables: Dict[str, str],
) -> str:
    normalized_task = (task_prompt or "").strip() or "完成当前需求"
    template, _ = _resolve_prompt_template(
        prompt_config=prompt_config,
        task_type=task_type,
        prompt_key="implementation",
        default_template=(
            "在目录 {scope_path} 下完成任务：{task_prompt}\n"
            "约束：所有新增或修改文件必须位于 {scope_path}；不要改动其他业务目录。"
        ),
    )

    variables = dict(template_variables)
    variables.update(
        {
            "task_prompt": normalized_task,
            "scope_path": _scope_label(scope_path),
        }
    )
    return _render_template(template, variables)


def _build_git_commit_command(
    *,
    mode: str,
    task_type: str,
    scope_path: str,
    prompt_config: Dict[str, Any],
    template_variables: Dict[str, str],
) -> tuple[str, Dict[str, str]]:
    template, template_source = _resolve_prompt_template(
        prompt_config=prompt_config,
        task_type=task_type,
        prompt_key="git_commit",
        default_template=_DEFAULT_PROMPT_CONFIG["prompts"]["git_commit"],
    )

    commit_message_cfg = prompt_config.get("commit_message_by_task_type", {})
    commit_message = str(
        commit_message_cfg.get(task_type)
        or commit_message_cfg.get("default")
        or _DEFAULT_PROMPT_CONFIG["commit_message_by_task_type"]["default"]
    )

    variables = dict(template_variables)
    variables.update(
        {
            "scope_path": _scope_label(scope_path),
            "git_add_target": scope_path or ".",
            "commit_message": commit_message,
        }
    )
    rendered_command = _render_template(template, variables)
    if mode != "real":
        rendered_command = "git提交"
    return rendered_command, {
        "prompt_template_key": "git_commit",
        "prompt_template_source": template_source,
    }


def _build_workflow_steps(
    *,
    task_type: str,
    task_prompt: str,
    mode: str,
    scope_path: str,
    prompt_config: Dict[str, Any],
    template_variables: Dict[str, str],
) -> list[Dict[str, Any]]:
    if task_type != "dev":
        return []

    track = _infer_dev_track(task_prompt)
    before_step = "$before-backend-dev" if track == "backend" else "$before-frontend-dev"
    check_step = "$check-backend" if track == "backend" else "$check-frontend"

    git_command, git_meta = _build_git_commit_command(
        mode=mode,
        task_type=task_type,
        scope_path=scope_path,
        prompt_config=prompt_config,
        template_variables=template_variables,
    )

    return [
        {"name": "$start", "command": "$start"},
        {"name": before_step, "command": before_step},
        {
            "name": "需求实现",
            "command": _build_scoped_task_prompt(
                task_prompt=task_prompt,
                scope_path=scope_path,
                task_type=task_type,
                prompt_config=prompt_config,
                template_variables=template_variables,
            ),
        },
        {"name": check_step, "command": check_step},
        {"name": "$finish-work", "command": "$finish-work"},
        {
            "name": "git提交",
            "command": git_command,
            "meta": git_meta,
        },
        {"name": "$record-session", "command": "$record-session"},
    ]


@dataclass
class _RunContext:
    run_id: str
    task_id: str
    task_prompt: str
    task_type: str
    max_rounds: int
    max_rounds_per_window: int
    mode: str
    model_id: str
    reasoning_level: str
    step_delay_seconds: float
    codex_bin: Optional[str]
    workspace_project_root: Path
    git_scope_path: str
    prompt_config_path: Optional[Path]
    prompt_config: Dict[str, Any]
    snapshot: Dict[str, Any]
    event_seq: int = 0
    interrupted: bool = False
    stop_requested: bool = False
    thread: Optional[threading.Thread] = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    workflow_steps: list[Dict[str, Any]] = field(default_factory=list)
    workflow_step_index: int = 0
    workflow_step_attempt: int = 0
    step_max_retry: int = 1
    dev_unfinished_threshold_n: int = 1
    dev_unfinished_streak: int = 0
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
        self.project_root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        self.runtime_root = runtime_root or (self.project_root / "runtime")
        self.store = RuntimeStore(runtime_root=self.runtime_root)
        self.runner_factory_map = runner_factory_map or {
            "mock": MockRunner,
            "real": RealRunner,
        }
        self.default_prompt_config_path = self.project_root / "orchestrator_prompts.json"
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
        dev_unfinished_threshold_n: int = 1,
        workspace_project_root: Optional[str] = None,
        git_scope_path: Optional[str] = None,
        prompt_config_path: Optional[str] = None,
    ) -> str:
        if max_rounds <= 0:
            raise ValueError("max_rounds 必须大于 0")
        if max_rounds_per_window <= 0:
            raise ValueError("max_rounds_per_window 必须大于 0")
        if step_max_retry < 0:
            raise ValueError("step_max_retry 必须大于等于 0")
        if dev_unfinished_threshold_n <= 0:
            raise ValueError("dev_unfinished_threshold_n 必须大于 0")
        if mode not in self.runner_factory_map:
            raise ValueError(f"不支持的 mode: {mode}")

        resolved_workspace = self._resolve_workspace_project_root(workspace_project_root)
        resolved_prompt_path = self._resolve_prompt_config_path(prompt_config_path)
        prompt_config = _load_prompt_config(resolved_prompt_path)
        resolved_scope = self._resolve_git_scope_path(git_scope_path, prompt_config=prompt_config)

        run_id = f"run-{uuid.uuid4().hex[:12]}"
        window_id = f"{run_id}-window-1"
        template_variables = self._build_template_variables(
            task_id=task_id,
            window_id=window_id,
            stage="window_1",
            changed_files="",
            summary="",
        )
        workflow_steps = _build_workflow_steps(
            task_type=task_type,
            task_prompt=task_prompt,
            mode=mode,
            scope_path=resolved_scope,
            prompt_config=prompt_config,
            template_variables=template_variables,
        )
        if workflow_steps:
            max_rounds = max(max_rounds, len(workflow_steps))
            max_rounds_per_window = max(max_rounds_per_window, len(workflow_steps))

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
            "workspace_project_root": str(resolved_workspace),
            "git_scope_path": resolved_scope,
            "prompt_config_path": str(resolved_prompt_path) if resolved_prompt_path else "",
            "current_workflow_step": workflow_steps[0]["name"] if workflow_steps else "",
            "current_workflow_step_index": 0,
            "current_workflow_step_attempt": 0,
            "current_workflow_step_status": "pending" if workflow_steps else "",
            "dev_unfinished_threshold_n": dev_unfinished_threshold_n,
            "window_switch_command": _WINDOW_SWITCH_COMMAND,
            "window_switch_semantics": _WINDOW_SWITCH_SEMANTICS,
            "updated_at": _utc_now(),
        }
        self.store.save_snapshot(snapshot)

        ctx = _RunContext(
            run_id=run_id,
            task_id=task_id,
            task_prompt=task_prompt,
            task_type=task_type,
            max_rounds=max_rounds,
            max_rounds_per_window=max_rounds_per_window,
            mode=mode,
            model_id=model_id,
            reasoning_level=reasoning_level,
            step_delay_seconds=step_delay_seconds,
            codex_bin=codex_bin,
            workspace_project_root=resolved_workspace,
            git_scope_path=resolved_scope,
            prompt_config_path=resolved_prompt_path,
            prompt_config=prompt_config,
            snapshot=snapshot,
            workflow_steps=workflow_steps,
            step_max_retry=step_max_retry,
            dev_unfinished_threshold_n=dev_unfinished_threshold_n,
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
            project_root=ctx.workspace_project_root,
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
                    if self._uses_fixed_workflow(ctx):
                        step_meta.update(dict(step.get("meta") or {}))
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
                    git_head_before = self._git_head_commit(ctx.workspace_project_root)
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
                                    self._append_policy_decision(
                                        ctx,
                                        step_name=step_name,
                                        decision_basis="workflow_completed_and_task_done",
                                        decision_result="continue_same_window",
                                        action="mark_completed",
                                        reason="task_done",
                                    )
                                    self._append_event(
                                        ctx,
                                        event_type="window_closed",
                                        command_text="",
                                        model_output_text="",
                                        operator_id="",
                                        meta={"reason": "completed"},
                                    )
                                    self._reset_unfinished_streak(ctx)
                                    self._update_status(ctx, "completed")
                                    break

                                switch_required, threshold_meta = self._mark_unfinished_round(ctx)
                                if switch_required:
                                    self._append_policy_decision(
                                        ctx,
                                        step_name=step_name,
                                        decision_basis="workflow_completed_but_task_unfinished",
                                        decision_result="start_new_window",
                                        action="start_new_window",
                                        reason="unfinished_threshold_reached",
                                        extra=threshold_meta,
                                    )
                                    switched = self._start_new_window(ctx, reason="workflow_completed")
                                    if not switched:
                                        self._update_status(ctx, "failed")
                                        break
                                    continue

                                self._append_policy_decision(
                                    ctx,
                                    step_name=step_name,
                                    decision_basis="workflow_completed_but_task_unfinished",
                                    decision_result="continue_same_window",
                                    action="continue_same_window",
                                    reason="unfinished_threshold_not_reached",
                                    extra=threshold_meta,
                                )
                                self._restart_workflow_in_same_window(ctx)
                                continue

                            self._append_policy_decision(
                                ctx,
                                step_name=step_name,
                                decision_basis="step_passed",
                                decision_result="continue_same_window",
                                action="continue_same_window",
                                reason="next_required_step",
                            )
                            continue

                        if result.done:
                            self._append_policy_decision(
                                ctx,
                                step_name=step_name,
                                decision_basis="step_passed_and_task_done",
                                decision_result="continue_same_window",
                                action="mark_completed",
                                reason="task_done",
                            )
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

                        self._append_policy_decision(
                            ctx,
                            step_name=step_name,
                            decision_basis="step_passed",
                            decision_result="continue_same_window",
                            action="continue_same_window",
                            reason="next_round",
                        )
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
                            self._append_policy_decision(
                                ctx,
                                step_name=step_name,
                                decision_basis="step_failed_retry_available",
                                decision_result="continue_same_window",
                                action="retry_current_step",
                                reason="retry_current_step",
                                extra={"failure_code": step_meta.get("failure_code", "")},
                            )
                            continue

                        if self._uses_fixed_workflow(ctx):
                            self._append_policy_decision(
                                ctx,
                                step_name=step_name,
                                decision_basis="step_failed_retry_exhausted",
                                decision_result="start_new_window",
                                action="start_new_window",
                                reason="retry_exhausted",
                                extra={"failure_code": step_meta.get("failure_code", "")},
                            )
                            switched = self._start_new_window(ctx, reason="retry_exhausted")
                            if not switched:
                                self._update_status(ctx, "failed")
                                break
                            continue

                        self._append_policy_decision(
                            ctx,
                            step_name=step_name,
                            decision_basis="step_failed_without_fixed_workflow",
                            decision_result="continue_same_window",
                            action="mark_failed",
                            reason="fatal_failure",
                            extra={"failure_code": step_meta.get("failure_code", "")},
                        )
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

    def _current_workflow_step(self, ctx: _RunContext) -> Dict[str, Any]:
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

    def _restart_workflow_in_same_window(self, ctx: _RunContext) -> None:
        if not ctx.workflow_steps:
            return
        ctx.workflow_step_index = 0
        ctx.workflow_step_attempt = 0
        ctx.snapshot["current_workflow_step"] = ctx.workflow_steps[0]["name"]
        ctx.snapshot["current_workflow_step_index"] = 0
        ctx.snapshot["current_workflow_step_attempt"] = 0
        ctx.snapshot["current_workflow_step_status"] = "pending"
        self._persist_snapshot(ctx)

    def _mark_unfinished_round(self, ctx: _RunContext) -> tuple[bool, Dict[str, Any]]:
        threshold = max(1, int(ctx.dev_unfinished_threshold_n))
        if ctx.task_type != "dev":
            return True, {"unfinished_streak": 0, "unfinished_threshold_n": threshold}

        ctx.dev_unfinished_streak += 1
        reached = ctx.dev_unfinished_streak >= threshold
        return reached, {
            "unfinished_streak": ctx.dev_unfinished_streak,
            "unfinished_threshold_n": threshold,
        }

    def _reset_unfinished_streak(self, ctx: _RunContext) -> None:
        ctx.dev_unfinished_streak = 0

    def _append_policy_decision(
        self,
        ctx: _RunContext,
        *,
        step_name: str,
        decision_basis: str,
        decision_result: str,
        action: str,
        reason: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        meta: Dict[str, Any] = {
            "step_name": step_name,
            "decision_basis": decision_basis,
            "decision_result": decision_result,
            "action": action,
            "reason": reason,
            "task_type": ctx.task_type,
            "window_index": int(ctx.snapshot.get("current_window_index", 0) or 0),
            "round_index_in_window": int(ctx.snapshot.get("current_round_index_in_window", 0) or 0),
            "global_round_index": int(ctx.snapshot.get("current_global_round_index", 0) or 0),
        }
        if decision_result == "start_new_window" or action == "start_new_window":
            meta["window_switch_command"] = _WINDOW_SWITCH_COMMAND
            meta["window_switch_semantics"] = _WINDOW_SWITCH_SEMANTICS
        if extra:
            meta.update(extra)
        self._append_event(
            ctx,
            event_type="policy_decision",
            command_text="",
            model_output_text="",
            operator_id="",
            meta=meta,
        )

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
        if ctx.workflow_steps:
            self._refresh_workflow_steps_for_current_window(ctx)
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
        self._reset_unfinished_streak(ctx)
        return True

    def _refresh_workflow_steps_for_current_window(self, ctx: _RunContext) -> None:
        ctx.prompt_config = _load_prompt_config(ctx.prompt_config_path)
        stage = f"window_{ctx.snapshot.get('current_window_index', 1)}"
        changed_files = ",".join(
            self._collect_changed_files(
                workspace_root=ctx.workspace_project_root,
                scope_path=ctx.git_scope_path,
            )[:20]
        )
        template_variables = self._build_template_variables(
            task_id=ctx.task_id,
            window_id=str(ctx.snapshot.get("current_window_id", "")),
            stage=stage,
            changed_files=changed_files,
            summary=ctx.last_model_output,
        )
        ctx.workflow_steps = _build_workflow_steps(
            task_type=ctx.task_type,
            task_prompt=ctx.task_prompt,
            mode=ctx.mode,
            scope_path=ctx.git_scope_path,
            prompt_config=ctx.prompt_config,
            template_variables=template_variables,
        )

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
            "workspace_project_root": str(ctx.workspace_project_root),
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

        has_changes = self._detect_git_changes(
            workspace_root=ctx.workspace_project_root,
            scope_path=ctx.git_scope_path,
        )
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

        if not commit_scope:
            commit_scope = ctx.git_scope_path or "."

        ctx.last_commit_id = commit_id
        ctx.last_commit_message = commit_message
        ctx.last_commit_scope = commit_scope

    def _resolve_workspace_project_root(self, workspace_project_root: Optional[str]) -> Path:
        candidate = Path(workspace_project_root).expanduser() if workspace_project_root else self.project_root
        if not candidate.is_absolute():
            candidate = (self.project_root / candidate).resolve()
        candidate = candidate.resolve()
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError(f"workspace_project_root 不存在或不是目录: {candidate}")

        cmd = ["git", "rev-parse", "--show-toplevel"]
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=candidate,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if proc.returncode != 0:
            raise ValueError(f"workspace_project_root 不是有效 Git 仓库: {candidate}")
        git_root = Path(str(proc.stdout or "").strip()).resolve()
        if not git_root.exists() or not git_root.is_dir():
            raise ValueError(f"无法解析 Git 仓库根目录: {candidate}")
        return git_root

    def _resolve_prompt_config_path(self, prompt_config_path: Optional[str]) -> Optional[Path]:
        if prompt_config_path:
            candidate = Path(prompt_config_path).expanduser()
            if not candidate.is_absolute():
                candidate = (self.project_root / candidate).resolve()
            candidate = candidate.resolve()
            if candidate.exists() and not candidate.is_file():
                raise ValueError(f"prompt_config_path 不是文件: {candidate}")
            return candidate

        if self.default_prompt_config_path.exists():
            return self.default_prompt_config_path
        return None

    def _resolve_git_scope_path(self, git_scope_path: Optional[str], *, prompt_config: Dict[str, Any]) -> str:
        raw_scope = git_scope_path
        if raw_scope is None:
            raw_scope = str(prompt_config.get("defaults", {}).get("git_scope_path") or "")
        return _normalize_scope_path(raw_scope)

    def _runtime_ignored_prefixes(self, workspace_root: Path) -> tuple[str, ...]:
        try:
            relative = self.runtime_root.resolve().relative_to(workspace_root.resolve())
        except ValueError:
            return ()
        normalized = relative.as_posix().strip("/")
        if not normalized:
            return ()
        return (f"{normalized}/",)

    @staticmethod
    def _iter_changed_paths(status_output: str) -> list[str]:
        paths: list[str] = []
        for raw_line in status_output.splitlines():
            line = raw_line.rstrip()
            if not line or len(line) < 4:
                continue
            path_part = line[3:].strip()
            parts = path_part.split(" -> ") if " -> " in path_part else [path_part]
            for item in parts:
                candidate = item.strip()
                if candidate.startswith('"') and candidate.endswith('"'):
                    candidate = candidate[1:-1]
                candidate = candidate.replace("\\", "/")
                if candidate:
                    paths.append(candidate)
        return paths

    def _collect_changed_files(self, *, workspace_root: Path, scope_path: str) -> list[str]:
        cmd = ["git", "status", "--porcelain", "--untracked-files=all"]
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if proc.returncode != 0:
            return []

        ignored_prefixes = self._runtime_ignored_prefixes(workspace_root)
        files: list[str] = []
        for changed in self._iter_changed_paths(str(proc.stdout or "")):
            if any(changed.startswith(prefix) for prefix in ignored_prefixes):
                continue
            if not _path_in_scope(changed, scope_path):
                continue
            files.append(changed)
        return files

    def _detect_git_changes(self, *, workspace_root: Path, scope_path: str) -> Optional[bool]:
        cmd = ["git", "status", "--porcelain", "--untracked-files=all"]
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if proc.returncode != 0:
            return None

        ignored_prefixes = self._runtime_ignored_prefixes(workspace_root)
        for changed in self._iter_changed_paths(str(proc.stdout or "")):
            if any(changed.startswith(prefix) for prefix in ignored_prefixes):
                continue
            if not _path_in_scope(changed, scope_path):
                continue
            return True
        return False

    def _git_head_commit(self, workspace_root: Path) -> str:
        cmd = ["git", "rev-parse", "HEAD"]
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if proc.returncode != 0:
            return ""
        return str(proc.stdout or "").strip()

    def _git_head_subject(self, workspace_root: Path) -> str:
        cmd = ["git", "show", "-s", "--format=%s", "HEAD"]
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=workspace_root,
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

        head_after = self._git_head_commit(ctx.workspace_project_root)
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
        enriched_meta["commit_message"] = enriched_meta.get("commit_message") or self._git_head_subject(
            ctx.workspace_project_root
        )
        enriched_meta["commit_scope"] = enriched_meta.get("commit_scope") or (ctx.git_scope_path or ".")
        enriched_meta["step_status"] = "passed"
        return RunnerStepResult(
            model_output_text=output_text,
            next_command_text=result.next_command_text,
            done=result.done,
            meta=enriched_meta,
        )

    @staticmethod
    def _build_template_variables(
        *,
        task_id: str,
        window_id: str,
        stage: str,
        changed_files: str,
        summary: str,
    ) -> Dict[str, str]:
        return {
            "task_id": task_id,
            "window_id": window_id,
            "stage": stage,
            "changed_files": changed_files,
            "summary": summary,
        }

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
