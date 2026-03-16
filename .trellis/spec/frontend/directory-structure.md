# Directory Structure

> 前端采用“页面三件套（HTML/CSS/JS）+ 业务目录隔离”。

---

## Directory Layout

```text
src/
├── frontend/
│   ├── index.html      # 编排控制台页面
│   ├── app.js          # 控制台交互与轮询逻辑
│   └── styles.css      # 控制台样式
book-manage/
├── index.html          # 示例业务页面
├── app.js              # 图书增删与本地存储
└── styles.css          # 示例页面样式
```

---

## Module Organization

- 一个页面对应一个独立目录（或固定三文件）。
- 页面脚本内部按“状态、请求、渲染、事件绑定”分段组织。
- 和编排控制台无关的示例业务页面放在独立目录（如 `book-manage/`）。

---

## Naming Conventions

- 目录与文件名使用 `kebab-case` 或既有简短名称（如 `book-manage`、`app.js`）。
- DOM id 使用 `kebab-case`，并与 `els` 键名一一对应。
- 类名语义化，状态类使用前缀（如 `is-hidden`、`round-tag failed`）。

---

## Examples

- 控制台结构示例：`src/frontend/index.html` + `src/frontend/app.js`
- 业务页面结构示例：`book-manage/index.html` + `book-manage/app.js`
- 静态挂载约束示例：`src/orchestrator/web.py`（`/book-manage` 路由）

---

## 反模式

- 在多个目录混放同一页面资源，导致静态挂载路径混乱。
- 页面脚本拆成过多碎文件但无清晰边界，增加维护成本。
