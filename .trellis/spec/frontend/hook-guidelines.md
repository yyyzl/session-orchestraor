# Hook Guidelines

> 本项目未使用 React Hook；采用“纯函数 + 闭包状态”复用逻辑。

---

## Overview

- 逻辑复用单元是函数，不以 `use*` 命名。
- 共享逻辑通过局部函数封装（如 `request`、`renderSnapshot`、`showAlert`）。
- 复用优先级：先函数抽取，再考虑模块拆分。

---

## Custom Hook Patterns

- 抽取“无 DOM 依赖”函数：如时间格式化、字符串转义。
- 抽取“弱 DOM 依赖”函数：接收节点引用而非内部全局查找。
- 避免把业务流程塞进单个超长函数，应按职责分段。

---

## Data Fetching

- 统一通过 `request(path, options)` 发起 fetch。
- 非 2xx 响应立即抛错，由调用方统一提示。
- 轮询由 `startPolling/stopPolling/pollOnce` 三段式管理。

---

## Naming Conventions

- 复用函数命名建议：
  - 请求类：`requestXxx` 或统一 `request`
  - 渲染类：`renderXxx` / `updateXxx`
  - 状态切换类：`setXxx` / `resetXxx`
- 回调函数使用动词短语，如 `appendSystemEvent`、`pollOnce`。

---

## Common Mistakes

- 未清理 `setInterval`，导致重复轮询。
- 同时在多个位置修改同一状态字段，产生 UI 抖动。
- 数据请求与 DOM 更新耦合过深，难以单测。

---

## 真实示例

- 轮询控制：`src/frontend/app.js`（`startPolling` / `stopPolling`）
- 请求封装：`src/frontend/app.js`（`request`）
- 本地复用函数：`book-manage/app.js`（`readBooks` / `saveBooks` / `render`）
