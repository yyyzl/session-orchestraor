from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .models import RunnerStepResult

try:
    from codex_app_server_multi_round import JsonRpcAppServerClient, resolve_codex_binary, select_model
except ModuleNotFoundError:
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from codex_app_server_multi_round import JsonRpcAppServerClient, resolve_codex_binary, select_model


class BaseRunner:
    def __init__(
        self,
        *,
        project_root: Path,
        model_id: str,
        reasoning_level: str,
        step_delay_seconds: float = 0.0,
        **_: Any,
    ) -> None:
        self.project_root = project_root
        self.model_id = model_id
        self.reasoning_level = reasoning_level
        self.step_delay_seconds = max(0.0, float(step_delay_seconds))

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def run_step(
        self,
        *,
        command_text: str,
        global_round_index: int,
        round_index_in_window: int,
        window_index: int,
        step_id: str,
    ) -> RunnerStepResult:
        raise NotImplementedError

    def _delay_if_needed(self) -> None:
        if self.step_delay_seconds > 0:
            time.sleep(self.step_delay_seconds)


class MockRunner(BaseRunner):
    def run_step(
        self,
        *,
        command_text: str,
        global_round_index: int,
        round_index_in_window: int,
        window_index: int,
        step_id: str,
    ) -> RunnerStepResult:
        self._delay_if_needed()

        text = (command_text or "").strip()
        if text == "$start":
            return RunnerStepResult(
                model_output_text="已完成会话初始化，准备进入开发流程。",
                next_command_text="",
                done=False,
                meta={"phase": "start", "step_status": "passed"},
            )

        if text in {"$before-frontend-dev", "$before-backend-dev"}:
            return RunnerStepResult(
                model_output_text=f"已加载开发规范：{text}。",
                next_command_text="",
                done=False,
                meta={"phase": "before-dev", "step_status": "passed"},
            )

        if text in {"$check-frontend", "$check-backend"}:
            return RunnerStepResult(
                model_output_text="已完成质量检查，当前窗口产物符合预期。",
                next_command_text="",
                done=False,
                meta={"phase": "check", "step_status": "passed"},
            )

        if text == "$finish-work":
            return RunnerStepResult(
                model_output_text="已完成收尾：更新说明并整理待确认项。",
                next_command_text="",
                done=False,
                meta={"phase": "finish-work", "step_status": "passed"},
            )

        if text == "git提交":
            return RunnerStepResult(
                model_output_text="已生成提交信息，等待执行提交。",
                next_command_text="",
                done=False,
                meta={
                    "phase": "git-commit",
                    "step_status": "passed",
                    "commit_id": f"mock-{global_round_index:04d}",
                    "commit_message": "feat: 增加 book-manage 前端页面与交互",
                    "commit_scope": "book-manage",
                },
            )

        if text == "$record-session":
            return RunnerStepResult(
                model_output_text="已记录本窗口会话摘要与变更信息。",
                next_command_text="",
                done=False,
                meta={"phase": "record-session", "step_status": "passed"},
            )

        if "实现" in text or "book-manage" in text:
            target_dir = self._resolve_target_dir(text)
            app_kind = self._resolve_mock_app_kind(text)
            if app_kind == "counter":
                self._ensure_counter_app(target_dir)
                summary = "counter 页面已生成：点击按钮可实时 +1。"
            else:
                self._ensure_book_manage_app(target_dir)
                summary = "book-manage 已生成：支持查看、新增、删除，且数据写入 localStorage。"
            return RunnerStepResult(
                model_output_text=summary,
                next_command_text="",
                done=True,
                meta={"phase": "implement", "step_status": "passed"},
            )

        return RunnerStepResult(
            model_output_text="mock runner 已执行当前步骤。",
            next_command_text="",
            done=False,
            meta={"phase": "default", "step_status": "passed"},
        )

    def _ensure_book_manage_app(self, app_dir: Path) -> None:
        app_dir.mkdir(parents=True, exist_ok=True)

        html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Book Manage</title>
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="./styles.css">
</head>
<body>
  <main class="shell">
    <header class="hero">
      <h1>Book Manage</h1>
      <p>本地管理你的图书清单</p>
    </header>
    <section class="panel">
      <h2>新增图书</h2>
      <form id="book-form">
        <label>
          书名
          <input id="book-title" required maxlength="80" placeholder="例如：深入理解计算机系统">
        </label>
        <label>
          作者
          <input id="book-author" required maxlength="60" placeholder="例如：Randal E. Bryant">
        </label>
        <button type="submit">新增</button>
      </form>
    </section>
    <section class="panel">
      <h2>图书列表</h2>
      <ul id="book-list" class="book-list"></ul>
      <p id="empty-hint" class="empty-hint">暂无图书，请先新增。</p>
    </section>
  </main>
  <script src="./app.js"></script>
</body>
</html>
"""
        css = """:root {
  --bg: #f0f4f8;
  --card: #ffffff;
  --text: #13253f;
  --accent: #0f766e;
  --danger: #be123c;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  font-family: "Segoe UI", "PingFang SC", sans-serif;
  color: var(--text);
  background:
    radial-gradient(circle at top right, #c7f9cc 0%, transparent 35%),
    linear-gradient(160deg, #f8fafc 0%, #e2e8f0 100%);
}
.shell {
  max-width: 860px;
  margin: 32px auto;
  padding: 20px;
  display: grid;
  gap: 16px;
}
.hero h1 { margin: 0; font-size: 2rem; letter-spacing: 0.02em; }
.hero p { margin: 8px 0 0; color: #334155; }
.panel {
  background: var(--card);
  border-radius: 14px;
  padding: 16px;
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
}
form {
  display: grid;
  gap: 10px;
}
label { display: grid; gap: 6px; font-weight: 600; }
input {
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 1rem;
}
button {
  width: fit-content;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 10px;
  padding: 10px 14px;
  font-weight: 700;
  cursor: pointer;
}
.book-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 10px;
}
.book-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px;
}
.book-meta { margin: 0; }
.book-author { color: #475569; font-size: 0.92rem; margin-top: 4px; }
.delete-btn {
  background: var(--danger);
  border-radius: 8px;
  padding: 8px 10px;
}
.empty-hint { color: #64748b; margin: 10px 0 0; }
@media (max-width: 640px) {
  .shell { margin: 20px auto; padding: 12px; }
  .book-item { align-items: flex-start; flex-direction: column; }
}
"""
        js = """(() => {
  const STORAGE_KEY = "book-manage-items";
  const form = document.getElementById("book-form");
  const titleInput = document.getElementById("book-title");
  const authorInput = document.getElementById("book-author");
  const listNode = document.getElementById("book-list");
  const emptyHint = document.getElementById("empty-hint");

  const readBooks = () => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
      return [];
    }
  };

  const saveBooks = (items) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  };

  let books = readBooks();

  const render = () => {
    listNode.innerHTML = "";
    emptyHint.style.display = books.length ? "none" : "block";
    books.forEach((book) => {
      const item = document.createElement("li");
      item.className = "book-item";

      const meta = document.createElement("div");
      meta.className = "book-meta";
      meta.innerHTML = `<strong>${book.title}</strong><p class="book-author">${book.author}</p>`;

      const button = document.createElement("button");
      button.className = "delete-btn";
      button.type = "button";
      button.textContent = "删除";
      button.addEventListener("click", () => {
        books = books.filter((candidate) => candidate.id !== book.id);
        saveBooks(books);
        render();
      });

      item.appendChild(meta);
      item.appendChild(button);
      listNode.appendChild(item);
    });
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const title = titleInput.value.trim();
    const author = authorInput.value.trim();
    if (!title || !author) return;
    books.unshift({
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      title,
      author,
    });
    saveBooks(books);
    form.reset();
    titleInput.focus();
    render();
  });

  render();
})();
"""
        (app_dir / "index.html").write_text(html, encoding="utf-8")
        (app_dir / "styles.css").write_text(css, encoding="utf-8")
        (app_dir / "app.js").write_text(js, encoding="utf-8")

    @staticmethod
    def _resolve_mock_app_kind(command_text: str) -> str:
        text = (command_text or "").lower()
        counter_markers = ("加一", "计数器", "counter", "increment", "+1")
        if any(marker in text for marker in counter_markers):
            return "counter"
        return "book-manage"

    def _ensure_counter_app(self, app_dir: Path) -> None:
        app_dir.mkdir(parents=True, exist_ok=True)

        html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Increment Counter</title>
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="./styles.css">
</head>
<body>
  <main class="counter-shell">
    <h1>计数器页面</h1>
    <p>点击按钮后，数字应立即加 1。</p>
    <div class="counter-box">
      <strong id="count-value">0</strong>
      <button id="increment-btn" type="button">+1</button>
    </div>
  </main>
  <script src="./app.js"></script>
</body>
</html>
"""
        css = """:root {
  --bg: #f3f7f9;
  --ink: #102a43;
  --accent: #0f766e;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  display: grid;
  place-items: center;
  font-family: "Segoe UI", "PingFang SC", sans-serif;
  background:
    radial-gradient(circle at 12% 12%, #ccfbf1 0%, transparent 35%),
    linear-gradient(150deg, #f8fafc 0%, var(--bg) 100%);
  color: var(--ink);
}
.counter-shell {
  width: min(560px, calc(100vw - 24px));
  border-radius: 14px;
  border: 1px solid #d9e2ec;
  background: #fff;
  padding: 20px;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.08);
}
h1 { margin: 0; }
p { margin: 10px 0 0; color: #486581; }
.counter-box {
  margin-top: 18px;
  display: flex;
  gap: 12px;
  align-items: center;
}
#count-value {
  min-width: 64px;
  font-size: 2.2rem;
  text-align: center;
}
#increment-btn {
  border: none;
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 1rem;
  font-weight: 700;
  color: #fff;
  background: var(--accent);
  cursor: pointer;
}
"""
        js = """(() => {
  const valueNode = document.getElementById("count-value");
  const incrementButton = document.getElementById("increment-btn");
  let count = 0;

  const render = () => {
    valueNode.textContent = String(count);
  };

  incrementButton.addEventListener("click", () => {
    count += 1;
    render();
  });

  render();
})();
"""

        (app_dir / "index.html").write_text(html, encoding="utf-8")
        (app_dir / "styles.css").write_text(css, encoding="utf-8")
        (app_dir / "app.js").write_text(js, encoding="utf-8")

    def _resolve_target_dir(self, command_text: str) -> Path:
        match = re.search(r"在目录\s+(.+?)\s+下完成任务", command_text or "")
        if not match:
            return self.project_root / "book-manage"

        raw_scope = match.group(1).strip().strip("'\"")
        if not raw_scope or raw_scope in {"仓库根目录", "."}:
            return self.project_root

        normalized = raw_scope.replace("\\", "/")
        if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
            return self.project_root / "book-manage"

        parts = [part for part in normalized.split("/") if part and part != "."]
        if any(part == ".." for part in parts):
            return self.project_root / "book-manage"
        if not parts:
            return self.project_root
        return self.project_root.joinpath(*parts)


def build_turn_sandbox_policy(sandbox_mode: str) -> dict[str, Any]:
    if sandbox_mode == "danger-full-access":
        return {"type": "dangerFullAccess"}
    if sandbox_mode == "workspace-write":
        return {
            "type": "workspaceWrite",
            "readOnlyAccess": {"type": "fullAccess"},
        }
    if sandbox_mode == "read-only":
        return {
            "type": "readOnly",
            "access": {"type": "fullAccess"},
        }
    raise ValueError(f"不支持的 sandbox_mode: {sandbox_mode}")


class RealRunner(BaseRunner):
    def __init__(
        self,
        *,
        project_root: Path,
        model_id: str,
        reasoning_level: str,
        step_delay_seconds: float = 0.0,
        client_factory=JsonRpcAppServerClient,
        codex_bin: Optional[str] = None,
        sandbox_mode: str = "danger-full-access",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            project_root=project_root,
            model_id=model_id,
            reasoning_level=reasoning_level,
            step_delay_seconds=step_delay_seconds,
            **kwargs,
        )
        self.client_factory = client_factory
        self.codex_bin = codex_bin
        self.sandbox_mode = sandbox_mode
        self.client = None
        self.thread_id: Optional[str] = None
        self.selected_model_id: Optional[str] = None

    def start(self) -> None:
        client_kwargs = {
            "command": [resolve_codex_binary(self.codex_bin), "app-server", "--listen", "stdio://"],
            "cwd": str(self.project_root),
        }
        try:
            self.client = self.client_factory(**client_kwargs)
        except TypeError:
            # 兼容不接受 cwd 参数的自定义 client_factory。
            self.client = self.client_factory(command=client_kwargs["command"])
        self.client.start()
        self.client.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "session-orchestrator-real-runner",
                    "title": "Session Orchestrator Real Runner",
                    "version": "1.0.0",
                },
                "capabilities": None,
            },
            timeout=30,
        )
        if self.model_id:
            self.selected_model_id = self.model_id
        else:
            model_resp = self.client.request(
                "model/list",
                {
                    "limit": 200,
                    "includeHidden": True,
                },
                timeout=30,
            )
            selected = select_model(model_resp.get("data", []))
            self.selected_model_id = selected.get("id")

        thread_resp = self.client.request(
            "thread/start",
            {
                "model": self.selected_model_id,
                "approvalPolicy": "never",
                "sandbox": self.sandbox_mode,
                "experimentalRawEvents": False,
                "persistExtendedHistory": False,
            },
            timeout=30,
        )
        self.thread_id = thread_resp.get("thread", {}).get("id")
        if not self.thread_id:
            raise RuntimeError("thread/start 未返回 thread.id")

    def stop(self) -> None:
        if self.client is not None:
            self.client.stop()

    def run_step(
        self,
        *,
        command_text: str,
        global_round_index: int,
        round_index_in_window: int,
        window_index: int,
        step_id: str,
    ) -> RunnerStepResult:
        if self.client is None or not self.thread_id:
            raise RuntimeError("real runner 尚未启动")
        self._delay_if_needed()

        turn_resp = self.client.request(
            "turn/start",
            {
                "threadId": self.thread_id,
                "approvalPolicy": "never",
                "sandboxPolicy": build_turn_sandbox_policy(self.sandbox_mode),
                "input": [
                    {
                        "type": "text",
                        "text": command_text,
                        "text_elements": [],
                    }
                ],
            },
            timeout=30,
        )
        turn_id = turn_resp.get("turn", {}).get("id")
        if not turn_id:
            raise RuntimeError("turn/start 未返回 turn.id")

        model_output = self.client.wait_turn_result_text(
            thread_id=self.thread_id,
            turn_id=turn_id,
            timeout=300,
        )
        done = self._is_done_output(model_output=model_output, global_round_index=global_round_index)
        next_command = "" if done else "请继续推进，直接输出下一步可执行结果。"
        return RunnerStepResult(
            model_output_text=model_output,
            next_command_text=next_command,
            done=done,
            meta={"turn_id": turn_id},
        )

    @staticmethod
    def _is_done_output(*, model_output: str, global_round_index: int) -> bool:
        if global_round_index < 2:
            return False
        text = (model_output or "").lower()
        markers = ("验收完成", "已完成", "task complete", "completed")
        return any(marker in text for marker in markers)
