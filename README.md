# Session Orchestrator

一个最小可用的“会话编排器”原型：用聊天式控制台驱动目标 Git 仓库内的开发任务，支持固定步骤链、运行快照与事件审计、人工插话与报告导出。

## 快速开始

### 1) 启动本地服务

```powershell
python src/run_server.py --host 127.0.0.1 --port 8765
```

浏览器打开：

- 控制台 UI：`http://127.0.0.1:8765/`
- 示例挂载（如果仓库里有 `book-manage/`）：`http://127.0.0.1:8765/book-manage/`

### 2) 在 UI 里选择目标仓库与作用域

左侧面板关键字段：

- `目标目录`：要被编排的 Git 仓库根目录（必须是 Git 仓库）
- `作用域路径`：仓库内相对路径，限制本轮变更范围，例如 `book-manage/`、`apps/web/`，也支持具体文件路径
- `模式`：
  - `mock`：不依赖外部模型，跑通流程与页面生成
  - `real`：通过 `codex app-server` 驱动真实执行

右侧聊天区：

- 第一条消息会创建一个新的 run 并开始执行
- 后续消息会作为人工插话插入当前 run

### 3) 运行测试

```powershell
python -m pytest -q
```

说明：仓库使用 `src/` 目录布局，已通过 `tests/conftest.py` 让 `pytest` 开箱即用，无需额外设置 `PYTHONPATH`。

### 4) 运行一次编排验证（可选）

```powershell
python src/execute_book_manage_validation.py --mode mock --timeout-seconds 120
```

验证完成后会在 `runtime/` 下生成：

- `runtime/runs/<run_id>.json`：运行快照
- `runtime/events/<run_id>.ndjson`：事件流水
- `runtime/reports/<run_id>.md`：可读报告导出

## 安全提示（real 模式）

`real` 模式会启动 `codex app-server` 并在你填写的 `目标目录` 内执行命令，可能包含 `git add/commit` 等写操作。建议在测试仓库或可回滚分支上使用，并确保 `作用域路径` 设置正确。

