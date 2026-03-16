# ReAct WorkItem 编排（方式 A）

## 🎯 Goal（目标）

把当前“固定步骤链编排器”升级为 **ReAct / Plan-and-Execute 的交互方式**：

- 用户只给一次“总目标 + 约束 + review 策略”。
- 系统生成并维护一个 **动态 WorkItem 队列**（不是固定 10 条，允许随执行演进）。
- 每次只推进 **1 个 WorkItem**，并在指定 review gate 处 **暂停等待人工确认**。
- 仍保持 **确定性的控制面**：可恢复、可审计、可回放、可熔断，不把控制权完全交给模型。

本任务选择 **方式 A**：每个 WorkItem 的执行复用现有固定步骤链（宏观确定性，微观在“实现”步骤内由模型执行）。

## 🧩 Background（背景）

当前项目已具备：

- 控制面：HTTP API + 前端控制台 + runtime 落盘（snapshot/events/report）。
- 执行面：`MockRunner` / `RealRunner` 两种执行模式（Real 通过 `codex app-server` 调用模型）。
- 决策面：以规则状态机为主（固定步骤链、重试、切窗、handoff 校验、git 后置校验等）。

现阶段的主要诉求是：把“会话式编排”升级成更贴近 **自主智能体** 的体验，解决上下文爆炸、目标遗忘、角色混乱，同时保持强可控与可观测。

## ✅ Scope（范围）

### In Scope

- 引入 **WorkItem**（工作项）概念，作为最小可 review 的推进单元。
- 引入 **Planner / Executor / Reviewer** 三种角色的隔离（可同模型不同 thread）。
- 引入 **ObservationPack（上下文压缩包）**：由控制面生成，作为 Planner/Reviewer 的输入。
- 引入 **Review Gate**（默认 N=2：command_review + human_review），通过后才允许提交并进入下一个 WorkItem。
- 引入 **同源失败断路器**：防止 Review/Fix 死循环。
- 引入 **Planner JSON 崩溃兜底**：连续失败触发人工接管。
- UI 增强：展示 WorkItem 列表、当前 WorkItem、review gate 状态，以及人工通过/打回按钮。
- API 增强：获取 WorkItem、人工 review、触发 replanning、暂停/恢复（如缺失）。

### Out of Scope（暂不做）

- 方式 B：在单个 WorkItem 内完全自由 ReAct（每条命令都由模型决策）。
- 并行执行多个 WorkItem（先保证串行闭环稳定）。
- 自动多模型评审（`model_review` 默认不启用，避免非确定性叠加）。
- 自动 squash 历史提交（可作为后续工具）。

## 👤 User Experience（交互体验）

用户操作流程：

1. 在控制台填写目标仓库与默认作用域（可选），选择 `mode=real/mock`。
2. 输入总目标（例如“实现 XXX 功能并补齐测试”）并开始运行。
3. 系统进入 `planning`：Planner 产出初始 WorkItem 队列（动态可调整）。
4. 系统选择第一个 WorkItem，进入 `executing_item` 并按固定步骤链执行至 `$finish-work`。
5. 系统自动跑 `command_review`（例如执行既有 `$check-*` 或内部命令检查）。
6. 进入 `human_review`，系统暂停，UI 显示检查结果、变更摘要、风险提示；用户点击“通过/打回”。
7. 通过：系统执行 `git提交` 与 `$record-session`，标记当前 WorkItem done，回到步骤 4 选下一个。
8. 打回：系统生成修复 WorkItem 或将当前 WorkItem 退回 `in_progress`，回到步骤 4。

## 🧱 Functional Requirements（功能需求）

### FR1. WorkItem 数据模型（事实源）

在 run snapshot 中持久化：

- `goal`：总目标文本。
- `phase`：planning/executing_item/reviewing_item/paused/completed/failed/stopped。
- `work_items[]`：动态队列，字段至少包含：
  - `id`：稳定 ID（不随重排变化）。
  - `root_id`：修复链追溯（初始 item 的 root_id = id；修复 item 继承 root_id）。
  - `title`：中文命令式短句（例如“增加登录接口参数校验”）。
  - `acceptance[]`：验收点列表（短句）。
  - `scope_path`：仓库内相对路径（目录或文件），强制在执行面校验。
  - `status`：planned/in_progress/blocked/done/failed。
  - `review_required`：默认 2，可按 item 覆盖。
  - `review_passed`：已通过次数。
  - `failure_streak`：同源失败计数（用于熔断）。
  - `notes`：handoff 摘要（<= 10 行）。
- `current_work_item_id`：当前正在推进的 item。

### FR2. Planner（决策面）与 ObservationPack

- Planner 只允许产出结构化 JSON，不允许直接改代码。
- 控制面负责组装 ObservationPack：
  - `goal`、`constraints`、`budgets`
  - `work_items_summary`（压缩）
  - `current_item_summary`
  - `recent_events`（最近 N 条关键事件，带 event_seq，长文本截断）
  - `repo_state`（diffstat、scope 内外变更统计、git head 等，能拿到则提供）

Planner 输出 JSON 契约（最小集）：

```json
{
  "action": "create_plan | update_plan | select_next_item | split_item | request_human | finish",
  "items": [],
  "selected_item_id": "wi_...",
  "reason": "短理由（1-3 句）",
  "requires_human_confirmation": false
}
```

### FR3. Executor（执行面）方式 A：固定步骤链包装

每个 WorkItem 的执行流程（方式 A）：

1. `$start`
2. `$before-frontend-dev` 或 `$before-backend-dev`（按本次任务类型）
3. `implement`：只允许围绕当前 WorkItem 的 acceptance，且强制 scope 限制
4. `$check-frontend` 或 `$check-backend`
5. `$finish-work`
6. `command_review`：确定性检查（可复用 `$check-*` 输出或新增内部检查步骤）
7. `human_review`：暂停等待人工确认
8. `git提交`
9. `$record-session`

约束：

- 任何写入必须在 `work_item.scope_path` 内，否则判 `OUT_OF_SCOPE` 并要求修正。
- 每次只允许推进一个 `current_work_item_id`，禁止跨 item 混改。

### FR4. Review Gate（默认 N=2）

默认 review 策略（MVP）：

- `N=2`
  - pass1: `command_review`（确定性：pytest/lint/已有 check step）
  - pass2: `human_review`（人工通过/打回）

规则：

- 未通过 review gate 不允许执行 `git提交`。
- 人工打回时：
  - 优先生成一个“修复 item”（继承 root_id），或把当前 item 退回 `in_progress`。

### FR5. 同源失败断路器（死循环熔断）

场景：某个 root item 派生出的修复 item 连续失败，系统不断重复修复。

规则（MVP 默认）：

- 针对同一个 `root_id`，若 `failure_streak > 3`：
  - 将该 root item 标记为 `blocked`
  - 写入 `circuit_breaker_tripped` 事件（包含失败原因摘要、最近失败证据）
  - 进入 `awaiting_human_item_review` / `paused` 等待人工介入

### FR6. Planner JSON 崩溃兜底

场景：Planner 连续输出非法 JSON 或非法 action。

规则（MVP 默认）：

- `max_planner_retry = 3`
- 连续 3 次解析失败或校验失败：
  - 写 `planner_invalid_output` 事件（含原始输出截断）
  - 强制进入 `awaiting_human`（人工接管），禁止继续循环调用 planner

## 🔌 API Requirements（接口）

在现有基础上新增/扩展（具体路径可调整，但需稳定）：

- `GET /api/runs/{run_id}/work-items`：返回 work_items 列表与当前项
- `POST /api/runs/{run_id}/human-review`：
  - body: `{ "work_item_id": "...", "decision": "approve|reject", "note": "..." }`
- `POST /api/runs/{run_id}/replan`：触发 planner（可选带新的约束/指令）
- `POST /api/runs/{run_id}/pause`、`POST /api/runs/{run_id}/resume`（若现有没有，则补齐）

## 🖥️ UI Requirements（控制台）

最小 UI 增强：

- WorkItem 列表：planned/in_progress/blocked/done 分类或标记
- 当前 WorkItem 详情：acceptance、scope、当前状态、review 进度
- Review Gate 面板：command_review 结果、human_review 按钮（通过/打回）
- blocked/熔断提示：显示 root_id 与失败摘要，提示人工下一步

## 🧪 Test Plan（测试计划）

新增/扩展后端单测（优先）：

- WorkItem 字段写入 snapshot，且可通过 API 拉取。
- `human_review` 触发状态机推进：通过后允许进入 git 提交；打回后生成修复 item 或回退状态。
- 同源失败断路器：超过阈值进入 blocked + paused。
- Planner JSON 崩溃兜底：连续失败后进入 awaiting_human。

前端可用性验证（手测为主，必要时补静态挂载测试）：

- UI 能展示 work_items 与当前项
- 人工通过/打回按钮可用，且能在事件流中看到对应记录

## 🗺️ Milestones（里程碑）

### M1：WorkItem 闭环（方式 A）

- WorkItem 持久化到 snapshot + API 读取
- 执行一个 WorkItem 后进入 human_review 暂停

### M2：Review Gate + 原子提交

- command_review 自动跑完再暂停人工
- 人工通过后才执行 git 提交与记录

### M3：ObservationPack + Planner 接入

- planner create/update/select 的 JSON 契约
- planner 崩溃兜底与审计事件

### M4：熔断与动态演进

- 同源失败断路器（blocked + awaiting_human）
- split/merge/update plan 的稳定策略

## ⚙️ Default Config（默认配置）

- `review_required_default = 2`（command_review + human_review）
- 每个 WorkItem 通过 review 后 **必须提交一次**（Atomic Commit）
- human_review 暂停点：在 command_review 完成后暂停（便于人工看到确定性结果）
- WorkItem scope：默认支持 item 级 `scope_path`（最强隔离）

