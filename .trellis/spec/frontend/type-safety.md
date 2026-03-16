# Type Safety

> 当前前端主代码为原生 JavaScript，通过“运行时校验 + 约定化结构”保障类型安全。

---

## Overview

- 现状：无 TypeScript 编译期类型系统。
- 策略：在边界处做显式转换（`String/Number/Boolean`）和空值兜底。
- 所有对外 JSON 数据按字段存在性与默认值消费。

---

## Type Organization

- 前端对象结构通过固定字段约定维护：
  - `state`: `runId/status/since/rounds`
  - `snapshot`: `status/current_window_index/current_step_id/...`
  - `event`: `event_type/global_round_index/meta/...`
- 后端返回结构作为“事实类型源”，由前端消费时做兼容处理。

---

## Validation

- DOM 输入统一 `trim()` 后再判断有效性。
- 时间字段先 `new Date(iso)`，`NaN` 时降级展示占位文本。
- API 请求统一检查 `response.ok`，非成功直接抛错。

---

## Common Patterns

- `String(raw ?? "")` 保证文本渲染安全类型。
- `Number(value || 0)` / `parseInt` 用于序号计算。
- `Array.isArray(parsed)` 验证 localStorage 反序列化结果。

---

## Forbidden Patterns

- 禁止直接信任外部 JSON 并无校验访问深层字段。
- 禁止把未定义值直接写入 DOM（会出现 `"undefined"` 文本）。
- 禁止为了“省事”删除输入校验分支。

---

## 真实示例

- 事件字段兼容处理：`src/frontend/app.js`
- localStorage 解析校验：`book-manage/app.js`
- 后端结构化返回：`src/orchestrator/web.py`
