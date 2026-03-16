# Frontend 开发规范

> 面向原生 HTML/CSS/JS 页面与编排控制台前端实现的约定。

---

## 适用范围

- 编排控制台前端：`src/frontend/index.html`、`src/frontend/app.js`、`src/frontend/styles.css`
- 业务示例页面：`book-manage/index.html`、`book-manage/app.js`、`book-manage/styles.css`
- 前端相关测试：`tests/test_web_static_mount.py`、`tests/test_mock_runner_counter_page.py`

---

## 规范索引

| 文档 | 说明 | 状态 |
|---|---|---|
| [Directory Structure](./directory-structure.md) | 前端目录划分与命名约定 | 已完成 |
| [Component Guidelines](./component-guidelines.md) | DOM 组件化组织、样式与可访问性 | 已完成 |
| [Hook Guidelines](./hook-guidelines.md) | 无框架场景下的状态逻辑复用约定 | 已完成 |
| [State Management](./state-management.md) | 会话态、本地持久态、服务端态管理 | 已完成 |
| [Type Safety](./type-safety.md) | 当前 JS 项目的类型安全边界与演进 | 已完成 |
| [Quality Guidelines](./quality-guidelines.md) | 代码质量、测试与评审清单 | 已完成 |

---

## 快速原则

1. 页面状态集中在 `state` 对象，DOM 引用集中在 `els`。
2. 与后端交互统一走 `request()`，错误统一抛出并提示。
3. 事件驱动更新 UI：收到事件后只更新受影响节点。
4. 业务页面优先小函数拆分，避免全局散落逻辑。
