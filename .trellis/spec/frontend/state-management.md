# State Management

> 状态管理遵循“页面内内存态 + 本地持久态 + 服务端运行态”三分法。

---

## Overview

- 不使用 Redux/Pinia 等全局库，当前均为页面级状态。
- 控制台页面状态集中在 `state` 对象。
- `book-manage` 业务数据落盘到 `localStorage`。
- 运行态真实来源以后端 `/api/runs/*` 为准。

---

## State Categories

- 本地内存态：`runId`、`status`、`since`、`rounds`（`src/frontend/app.js`）。
- 本地持久态：`book-manage-items`（`book-manage/app.js`）。
- 服务端态：`snapshot/events/report`（通过 API 获取）。
- 派生态：状态徽标、轮次卡片、空列表提示等 UI 派生结果。

---

## When to Use Global State

- 当前无跨页面共享需求，不引入全局状态容器。
- 仅当出现“跨多个页面长期共享并频繁联动”的状态，再评估全局库。
- 在此之前优先函数拆分与 URL / API 驱动。

---

## Server State

- 以轮询方式增量同步事件：`/events?since=...`。
- 先拉 `snapshot` 再拉 `events`，保持状态与流水一致。
- 终态（`completed/failed/stopped`）后必须停止轮询并显示收尾提示。

---

## Common Mistakes

- 忘记重置 `since`，导致新运行漏读或重复读事件。
- 终态后未停止轮询，造成无效请求。
- 把服务端真值状态改写成本地“猜测状态”，导致展示不一致。

---

## 真实示例

- 控制台状态对象：`src/frontend/app.js`
- 本地持久化读写：`book-manage/app.js`
- 事件与快照接口：`src/orchestrator/web.py`
