# Logging Guidelines

> 本项目日志以“事件流水 + 必要控制台输出”为主。

---

## Overview

- 当前未引入 `logging` 框架，运行态审计依赖 `runtime/events/*.ndjson`。
- 服务访问日志默认关闭（`web.Handler.log_message` 为空实现）。
- CLI 启动/停止信息使用 `print` 输出。

---

## Log Levels

- `info`：正常流程节点（通过事件 `step_started/step_finished` 表达）。
- `warn`：重试、阻断、策略降级（如 `step_retrying`）。
- `error`：运行失败或异常（事件 `error` + `meta.error`）。

> 若未来接入 `logging`，请保持上述语义映射不变。

---

## Structured Logging

- 事件采用 NDJSON，每行一个 JSON 对象。
- 必备字段：`event_id`、`run_id`、`window_index`、`global_round_index`、`event_type`、`timestamp`、`meta`。
- 快照用于聚合最新状态，不代替事件流水。

---

## What to Log

- 每个步骤的输入命令与模型输出。
- 窗口切换、重试决策、人工插话等关键控制事件。
- 运行结束态（`completed/failed/stopped`）与原因元数据。

---

## What NOT to Log

- 不记录密钥、token、绝对私密路径等敏感信息。
- 不把完整大文本重复写入多个事件字段（避免日志膨胀）。
- 不在 `print` 中打印结构化敏感 payload。

---

## 真实示例

- 事件写入与报告导出：`src/orchestrator/storage.py`
- 事件字段校验：`src/orchestrator/validation.py`
- 控制台输出：`src/run_server.py`、`src/execute_book_manage_validation.py`
