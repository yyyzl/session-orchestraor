from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.runners import MockRunner


class MockRunnerCounterPageTests(unittest.TestCase):
    def test_implement_counter_task_generates_increment_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = MockRunner(
                project_root=root,
                model_id="mock-model",
                reasoning_level="medium",
            )
            command = (
                "在目录 book-manage/ 下完成任务：生成一个按一下就加一的前端页面。\n"
                "约束：所有新增或修改文件必须位于 book-manage/；不要改动其他业务目录。"
            )
            result = runner.run_step(
                command_text=command,
                global_round_index=1,
                round_index_in_window=1,
                window_index=1,
                step_id="step-1",
            )

            self.assertTrue(result.done)
            html = (root / "book-manage" / "index.html").read_text(encoding="utf-8")
            js = (root / "book-manage" / "app.js").read_text(encoding="utf-8")
            self.assertIn("increment-btn", html)
            self.assertIn("count-value", html)
            self.assertIn("count += 1", js)


if __name__ == "__main__":
    unittest.main()
