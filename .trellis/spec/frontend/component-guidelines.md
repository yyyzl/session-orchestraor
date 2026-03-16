# Component Guidelines

> 当前以前端原生 DOM 组件为主，不依赖 React/Vue 组件体系。

---

## Overview

- 组件以“函数 + 模板字符串 + DOM 节点创建”方式组织。
- 复用通过“生成函数 + 局部更新函数”实现，不引入复杂框架抽象。
- 组件状态变化通过 className / textContent / innerHTML 驱动。

---

## Component Structure

- 先定义 `state` 与 `els`，再定义渲染函数、最后绑定事件。
- 动态块优先 `document.createElement` 拼装，避免大段字符串拼接。
- 页面切换统一通过 `setViewMode()` 一类函数控制 class。

---

## Props Conventions

- 无框架 props；改用函数参数传递事件对象或数据对象。
- 所有外部输入先 `trim()` / `String()`，再进入渲染。
- 关键展示内容在插入 HTML 前做转义（如 `escapeHtml`）。

---

## Styling Patterns

- 样式独立放在 `styles.css`，脚本只管理类名切换。
- 使用语义化块名（`round-card`、`round-bubble`、`system-event`）。
- 状态样式通过修饰类表达（如 `failed`、`retrying`、`pending`）。

---

## Accessibility

- 关键告警位使用 `role="alert"` 与 `aria-live`。
- 表单控件通过 `label` 关联，提高可读与可点击区域。
- 按钮明确 `type="button"` / `type="submit"`，防止误提交。

---

## Common Mistakes

- 在 `innerHTML` 中直接插入未转义文本，产生 XSS 风险。
- 事件回调里重复查找 DOM，造成性能与可读性下降。
- 组件更新后未滚动到底部，导致实时日志可见性差。

---

## 真实示例

- 控制台卡片渲染：`src/frontend/app.js`（`ensureRoundCard` / `updateRoundFromEvent`）
- 告警与可访问性：`src/frontend/index.html`
- 业务列表组件化生成：`book-manage/app.js`
