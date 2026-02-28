from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .runners import MockRunner, RealRunner
from .storage import RuntimeStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class _RunContext:
    run_id: str
    task_prompt: str
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


class SessionOrchestrator:
    def __init__(
        self,
        *,
        project_root: Optional[Path] = None,
        runtime_root: Optional[Path] = None,
        runner_factory_map: Optional[Dict[str, Callable[..., Any]]] = None,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.runtime_root = runtime_root or (self.project_root / "session-orchestrator" / "runtime")
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
    ) -> str:
        if max_rounds <= 0:
            raise ValueError("max_rounds 必须大于 0")
        if max_rounds_per_window <= 0:
            raise ValueError("max_rounds_per_window 必须大于 0")
        if mode not in self.runner_factory_map:
            raise ValueError(f"不支持的 mode: {mode}")

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
            "updated_at": _utc_now(),
        }
        self.store.save_snapshot(snapshot)

        ctx = _RunContext(
            run_id=run_id,
            task_prompt=task_prompt,
            max_rounds=max_rounds,
            max_rounds_per_window=max_rounds_per_window,
            mode=mode,
            model_id=model_id,
            reasoning_level=reasoning_level,
            step_delay_seconds=step_delay_seconds,
            codex_bin=codex_bin,
            snapshot=snapshot,
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

                    next_global_round = int(ctx.snapshot["current_global_round_index"]) + 1
                    next_round_in_window = int(ctx.snapshot["current_round_index_in_window"]) + 1
                    step_id = f"step-{next_global_round}"
                    ctx.snapshot["current_global_round_index"] = next_global_round
                    ctx.snapshot["current_round_index_in_window"] = next_round_in_window
                    ctx.snapshot["current_step_id"] = step_id
                    self._persist_snapshot(ctx)

                    self._append_event(
                        ctx,
                        event_type="step_started",
                        command_text=current_command,
                        model_output_text="",
                        operator_id="",
                        meta={},
                    )
                    self._append_event(
                        ctx,
                        event_type="model_input",
                        command_text=current_command,
                        model_output_text="",
                        operator_id="",
                        meta={},
                    )

                step_started_at = datetime.now(timezone.utc)
                result = runner.run_step(
                    command_text=current_command,
                    global_round_index=next_global_round,
                    round_index_in_window=next_round_in_window,
                    window_index=int(ctx.snapshot["current_window_index"]),
                    step_id=step_id,
                )
                duration_ms = int((datetime.now(timezone.utc) - step_started_at).total_seconds() * 1000)

                with ctx.lock:
                    self._append_event(
                        ctx,
                        event_type="model_output",
                        command_text=current_command,
                        model_output_text=result.model_output_text,
                        operator_id="",
                        duration_ms=duration_ms,
                        meta=result.meta,
                    )
                    self._append_event(
                        ctx,
                        event_type="step_finished",
                        command_text=current_command,
                        model_output_text=result.model_output_text,
                        operator_id="",
                        duration_ms=duration_ms,
                        meta={},
                    )

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
