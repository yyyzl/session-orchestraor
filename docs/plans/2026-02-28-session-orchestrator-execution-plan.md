# 会话编排器执行前文档（含真实运行存盘规范）

## 简要总结

基于你现有仓库，先在 `session-orchestrator/` 内实现一个最小可用会话编排器（后端+简单前端），核心是“持续可观测 + 人工可插话 + 输入输出可审计存盘”；并用它验证驱动 `book-manage/` 生成纯前端图书管理系统（查看/新增/删除）。
参考实现文件为 `codex_app_server_skill_validation_external.py`，它仅作“最小 demo 参考”，不等同最终需求。

## 文档落盘目标

- 计划文档目标路径：`docs/plans/2026-02-28-session-orchestrator-execution-plan.md`
- 文档必须显式标注：`codex_app_server_skill_validation_external.py` 为参考原型，最终实现需扩展状态建模与存盘字段。

## 关键新增要求（你本轮补充）

1. 真实运行过程中的输入/输出必须持续存盘，不仅是 Markdown 汇总。
2. 存盘结构必须包含“第几次上下文窗口”等会话编排关键信息。
3. `skill_validation_external_rounds.md` 只能作为可读导出，不作为唯一事实来源。

## 参考代码定位与复用边界

1. 参考文件：`codex_app_server_skill_validation_external.py`
2. 可复用：
   - 外部模型决策循环思路
   - 多轮回合组织方式
   - 输出渲染为 Markdown 的导出逻辑
3. 必须重构/新增：
   - 会话窗口维度（window）状态机
   - 前端可视化事件流
   - 结构化持久化（JSONL/JSON）与恢复能力
   - 人工消息打断与审计日志

## 存盘设计（最终事实源）

### 1) 运行快照文件（覆盖写）

- 路径：`session-orchestrator/runtime/runs/{run_id}.json`
- 用途：当前运行态、可恢复定位
- 核心字段：
  - `run_id`
  - `task_id`
  - `task_type`
  - `status`（running/paused/stopped/completed/failed）
  - `current_window_index`（第几次上下文窗口，从 1 开始）
  - `current_window_id`
  - `current_round_index_in_window`
  - `current_step_id`
  - `mode`（mock/real）
  - `model_id`
  - `reasoning_level`
  - `updated_at`

### 2) 事件流水文件（追加写）

- 路径：`session-orchestrator/runtime/events/{run_id}.ndjson`
- 用途：完整审计、前端日志回放
- 每行一个事件，建议字段：
  - `event_id`
  - `run_id`
  - `window_index`（第几次上下文窗口）
  - `window_id`
  - `round_index_in_window`
  - `global_round_index`
  - `step_id`
  - `event_type`（step_started/step_finished/model_input/model_output/window_started/window_closed/operator_message/interrupted/error）
  - `command_text`（当前输入命令/提示词）
  - `model_output_text`（模型输出原文）
  - `operator_id`（人工介入时）
  - `timestamp`
  - `duration_ms`（可选）
  - `meta`（可扩展字典）

### 3) 可读导出文件（非事实源）

- 路径：`session-orchestrator/runtime/reports/{run_id}.md`
- 用途：人工阅读与复盘
- 来源：由 `runs/{run_id}.json` + `events/{run_id}.ndjson` 生成

## 前端最小页面要求（MVP）

1. 状态板：
   - 是否执行中
   - 当前窗口（`window_index/window_id`）
   - 当前窗口第几轮
   - 当前步骤
2. 即时消息框：
   - 输入人工消息
   - 发送后立即写事件并触发中断逻辑
3. 日志区：
   - 按时间显示 `command_text` 与 `model_output_text`
   - 显示窗口切换事件（新开窗口/复用窗口）

## 强流程管控补充（从 brainstorm 收敛到执行）

### 1) 单窗口固定步骤链（不可缺失）

每个 `dev` 窗口必须按顺序完成以下步骤：

1. `$start`
2. `$before-frontend-dev` 或 `$before-backend-dev`（按任务类型命中其一或同时命中）
3. 需求实现（本轮业务指令）
4. `$check-frontend` 或 `$check-backend`
5. `$finish-work`
6. `git提交`
7. `$record-session`

### 2) 步骤状态与质量门

1. 步骤状态统一使用：`pending/running/passed/failed/retrying/skipped/interrupted`。
2. 任一步骤未通过，当前窗口不得标记完成。
3. 单步骤默认最大重试次数：`1`（超限后进入策略判定）。
4. 每步骤执行后必须写结构化回执（至少包含 `step_id`、`status`、`duration_ms`、`next_step`）。

### 3) 切窗与 handoff 强约束

1. `dev` 任务只有在固定步骤链完整通过后，才允许输出 `start_new_window`。
2. 切窗前必须进行 `Context Handoff` 校验，缺少关键字段禁止切窗：
   - `task_goal`
   - `last_commit_id`
   - `last_commit_message`
3. 新窗口首条指令必须包含：
   - 任务目标
   - 上一轮提交信息
   - 下一步动作

### 4) git 提交策略（按任务类型）

1. `planning`：无代码变更时，允许且要求空提交（`git commit --allow-empty`），并记录原因与提交哈希。
2. `dev`：无代码变更时，禁止空提交；`git提交` 步骤判定失败并进入修正/重试。
3. 提交粒度固定为每窗口一次（窗口成功后提交）。

## 验证任务与验收

1. 编排器启动后，执行“实现 book-manage 前端（查看/新增/删除）”任务。
2. 运行中可见实时状态、输入、输出、窗口与轮次。
3. 存盘文件可证明：
   - 每次窗口编号连续可追踪
   - 每轮输入输出可回放
   - 人工消息和中断事件可审计
4. `book-manage` 功能验收：
   - 首页查看
   - 新增图书
   - 删除图书
   - 数据 localStorage 持久化
5. 流程验收：
   - 固定步骤链无漏步（`$start` 到 `$record-session`）
   - 步骤失败会触发重试或阻断，不会直接跳过
   - `dev` 场景切窗前具备完整 handoff 字段
   - `git提交` 命中任务类型策略（`dev` 禁空提交，`planning` 强制空提交）

## 实施顺序（执行时）

1. 先建 `session-orchestrator` 后端骨架与存盘层。
2. 落地固定步骤链状态机与质量门（含重试、阻断、下一步决策）。
3. 接入 mock runner，打通前端实时显示。
4. 接入 real runner（参考 `codex_app_server_skill_validation_external.py` 适配）。
5. 完成人工消息打断与事件审计。
6. 落地 `start_new_window` 前的 handoff 校验与提交策略校验。
7. 用编排器驱动产出 `book-manage` 并验收。
8. 导出运行报告 md，和结构化日志交叉核对一致性。

## 假设与默认值

1. 默认 `mode=mock`，联调完成后切 `real`。
2. 默认 `task_type=dev`。
3. 默认 `window_index` 从 1 开始，严格递增。
4. 默认结构化日志为唯一事实源，Markdown 仅为派生结果。

## 工具调用简报

- 本轮未调用外部工具；基于你新增约束对计划进行了完整替换与收敛。
