# Database Guidelines

> 本项目当前**无关系型数据库**，运行态持久化由文件存储承担。

---

## Overview

- 当前方案：`RuntimeStore` 使用 JSON / NDJSON / Markdown 存储会话运行数据。
- 存储路径：
  - `runtime/runs/{run_id}.json`（快照）
  - `runtime/events/{run_id}.ndjson`（事件流水）
  - `runtime/reports/{run_id}.md`（导出报告）
- 并发控制：文件写入必须持有 `threading.Lock`。

---

## Query Patterns

- 读取快照：`load_snapshot(run_id)`，不存在时抛 `FileNotFoundError`。
- 追加事件：`append_event(event)`，一次一行写入 NDJSON。
- 读取事件：`load_events(run_id)`，按行解析并过滤空行。
- 导出报告：`export_report(run_id)` 基于快照与事件重建可读报告。

> 约束：其他模块不得直接读写 `runtime/*`，必须走 `RuntimeStore`。

---

## Migrations

- 当前无数据库迁移系统（无 Alembic/ORM migration）。
- “模式变更”采用文档化的字段扩展策略：
  1. 新字段仅追加，不重命名既有关键字段。
  2. 新增字段需在 `validation.py` 的必填校验中同步更新。
  3. 需要变更历史结构时，先补兼容读取逻辑，再执行写入升级。

---

## Naming Conventions

- JSON 字段使用 `snake_case`（如 `task_id`、`current_window_index`）。
- 以 `run_id` 为核心分区键；事件按 `event_seq` 递增。
- 文件命名固定：`{run_id}.json` / `{run_id}.ndjson` / `{run_id}.md`。

---

## Common Mistakes

- 绕过 `RuntimeStore` 直接 `Path.write_text`，导致并发写覆盖。
- 事件写入不按 NDJSON 一行一对象，后续解析失败。
- 修改快照字段后未同步 `validate_run_consistency` 校验项。

---

## 真实示例

- 存储实现：`src/orchestrator/storage.py`
- 校验约束：`src/orchestrator/validation.py`
- 快照字段生产：`src/orchestrator/service.py`
