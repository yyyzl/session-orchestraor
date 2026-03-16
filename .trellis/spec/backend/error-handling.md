# Error Handling

> 异常按“业务层抛出 -> Web 层映射 -> 前端消费”处理。

---

## Overview

- service 层负责参数/状态校验并抛出明确异常类型。
- web 层统一捕获异常并映射 HTTP 状态码。
- 未知异常兜底 500，并返回 JSON `{ "error": "..."} `。

---

## Error Types

- `ValueError`：参数非法或配置非法（如 `max_rounds <= 0`）。
- `KeyError`：运行实例不存在（如 `run_id` 不存在）。
- `RuntimeError`：状态冲突或流程非法（如不允许插话）。
- `FileNotFoundError`：快照/静态文件缺失。

---

## Error Handling Patterns

- 输入校验前置：在 `start_run` 入口集中校验，尽早失败。
- 文件范围校验：路径解析失败立即 `ValueError`，不做隐式纠正。
- 大流程兜底：线程循环中捕获 `Exception`，写入错误事件并置失败状态。

---

## API Error Responses

- `400`：`ValueError`
- `404`：`KeyError` / `FileNotFoundError`
- `409`：`RuntimeError`
- `500`：其他未预期异常
- 返回体统一 JSON：`{"error": "<message>"}`

---

## Common Mistakes

- 在 service 层吞异常后返回“空成功”，导致状态与事件不一致。
- web 层直接透传 Python traceback 给前端（应返回简洁错误文本）。
- 抛异常时信息过短（如仅 `"invalid"`），排障困难。

---

## 真实示例

- 参数校验与抛错：`src/orchestrator/service.py`
- HTTP 异常映射：`src/orchestrator/web.py`
- 文件不存在错误：`src/orchestrator/storage.py`
