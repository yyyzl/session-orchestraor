# ReAct WorkItem 编排（方式 A）契约

> 目标：在不破坏现有 “classic 固定步骤链” 的前提下，引入 `workflow_mode=work_items` 的新编排模式，
> 支持 WorkItem 队列、Review Gate（command_review + human_review）、以及 pause/resume 控制。

---

## 1. 启动参数（Start Run）

### POST `/api/runs/start`

在现有 body 基础上新增：

- `workflow_mode`: `"classic" | "work_items"`（默认 `"classic"`）

说明：

- `classic`：保持现有行为（`$start → before-dev → implement → $check-* → $finish-work → git提交 → $record-session`）。
- `work_items`：启用 WorkItem 编排（方式 A），每个 WorkItem 按固定步骤链推进并在 `human_review` 暂停。

---

## 2. Snapshot 扩展字段（事实源）

当 `workflow_mode="work_items"` 时，snapshot 追加以下字段（不影响 classic）：

- `goal`: `string` 总目标（等同于用户首条 prompt，但后续不应被覆盖）
- `phase`: `planning | executing_item | reviewing_item | paused | completed | failed | stopped`
- `work_items`: `WorkItem[]` 动态队列
- `current_work_item_id`: `string` 当前推进项
- `pause_reason`: `string`（可选）例如：`human_review` / `operator_message` / `circuit_breaker`
- `review_required_default`: `number` 默认 `2`
- `circuit_breaker_threshold`: `number` 默认 `3`
- `max_planner_retry`: `number` 默认 `3`（MVP 可不启用 planner 时仍保留字段）

### WorkItem 最小字段集

```json
{
  "id": "wi_xxxxxxxx",
  "root_id": "wi_xxxxxxxx",
  "title": "中文命令式短句",
  "acceptance": ["..."],
  "scope_path": "book-manage/",
  "status": "planned | in_progress | blocked | done | failed",
  "review_required": 2,
  "review_passed": 0,
  "failure_streak": 0,
  "notes": "handoff 摘要（<= 10 行）"
}
```

允许扩展字段（用于 UI 展示与审计）：

- `last_command_review`: `{ ok: boolean, summary: string, out_of_scope_files?: string[] }`
- `last_human_review`: `{ decision: "approve|reject", note: string, at: string }`

---

## 3. API 契约

### GET `/api/runs/{run_id}/work-items`

响应（建议）：

```json
{
  "run_id": "xxx",
  "goal": "...",
  "phase": "reviewing_item",
  "current_work_item_id": "wi_...",
  "work_items": [],
  "current_item": {}
}
```

### POST `/api/runs/{run_id}/human-review`

请求：

```json
{ "work_item_id": "wi_...", "decision": "approve|reject", "note": "..." }
```

语义：

- `approve`：通过 review gate（human_review），允许推进到 `git提交`。
- `reject`：生成修复 WorkItem（继承 `root_id`）或回退当前 item 状态；MVP 优先生成修复 item。

响应：

```json
{ "ok": true }
```

### POST `/api/runs/{run_id}/pause`

请求（可选）：

```json
{ "reason": "human_request", "note": "..." }
```

响应：

```json
{ "ok": true }
```

### POST `/api/runs/{run_id}/resume`

响应：

```json
{ "ok": true }
```

### POST `/api/runs/{run_id}/replan`

MVP 语义：

- 触发 planning（可能追加/更新 work_items），并写入审计事件。
- 若当前处于暂停态，可选择一并 resume。

响应：

```json
{ "ok": true }
```

---

## 4. 错误与 HTTP 映射

沿用现有 web 层规范：

- `400`：`ValueError`（参数非法）
- `404`：`KeyError` / `FileNotFoundError`（run 不存在 / 快照缺失）
- `409`：`RuntimeError`（状态冲突：例如非 human_review 阶段却提交 human-review）
- `500`：兜底

错误体统一：

```json
{ "error": "..." }
```

