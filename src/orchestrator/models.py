from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class RunnerStepResult:
    model_output_text: str
    next_command_text: str
    done: bool
    meta: Dict[str, Any] = field(default_factory=dict)
