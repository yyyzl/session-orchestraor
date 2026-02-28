from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .storage import RuntimeStore


def _is_continuous(values: List[int]) -> bool:
    if not values:
        return False
    sorted_values = sorted(set(values))
    expected = list(range(sorted_values[0], sorted_values[-1] + 1))
    return sorted_values == expected and sorted_values[0] == 1


def validate_run_consistency(*, runtime_root: Path, run_id: str) -> Dict[str, Any]:
    store = RuntimeStore(runtime_root=runtime_root)
    snapshot = store.load_snapshot(run_id)
    events = store.load_events(run_id)

    event_types = [str(event.get("event_type", "")) for event in events]
    window_indices = [int(event.get("window_index", 0) or 0) for event in events]
    has_model_input = "model_input" in event_types
    has_model_output = "model_output" in event_types
    checks = {
        "snapshot_exists": bool(snapshot),
        "events_exists": bool(events),
        "window_index_continuous": _is_continuous(window_indices),
        "has_model_io": has_model_input and has_model_output,
        "events_match_snapshot_run_id": all(str(event.get("run_id", "")) == run_id for event in events),
        "snapshot_has_required_fields": all(
            field in snapshot
            for field in (
                "run_id",
                "task_id",
                "task_type",
                "status",
                "current_window_index",
                "current_window_id",
                "current_round_index_in_window",
                "current_step_id",
                "mode",
                "model_id",
                "reasoning_level",
                "updated_at",
            )
        ),
        "events_have_required_fields": all(
            all(
                field in event
                for field in (
                    "event_id",
                    "run_id",
                    "window_index",
                    "window_id",
                    "round_index_in_window",
                    "global_round_index",
                    "step_id",
                    "event_type",
                    "command_text",
                    "model_output_text",
                    "operator_id",
                    "timestamp",
                    "meta",
                )
            )
            for event in events
        ),
    }
    ok = all(checks.values())
    return {
        "ok": ok,
        "run_id": run_id,
        "status": snapshot.get("status"),
        "event_count": len(events),
        "checks": checks,
    }
