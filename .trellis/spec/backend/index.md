# Backend 开发规范

> 面向 `src/orchestrator` 与后端启动脚本的落地约定。

---

## 适用范围

- Python 后端核心：`src/orchestrator/`
- 后端启动脚本：`src/run_server.py`
- JSON-RPC 客户端工具：`src/codex_app_server_multi_round.py`
- 后端测试：`tests/test_workflow_control.py`、`tests/test_web_static_mount.py`

---

## 规范索引

| 文档 | 说明 | 状态 |
|---|---|---|
| [Directory Structure](./directory-structure.md) | 模块边界、目录组织、命名规则 | 已完成 |
| [Database Guidelines](./database-guidelines.md) | 当前持久化方案与“无 DB”约束 | 已完成 |
| [Error Handling](./error-handling.md) | 异常分层、HTTP 映射、失败事件 | 已完成 |
| [Logging Guidelines](./logging-guidelines.md) | 运行日志策略与事件流水 | 已完成 |
| [Quality Guidelines](./quality-guidelines.md) | 代码质量、测试与评审清单 | 已完成 |

---

## 快速原则

1. 先在 service 层做参数校验，再进入 runner 执行。
2. 统一通过 `RuntimeStore` 读写运行态，不绕过存储层。
3. Web 层只做协议转换：异常映射 + JSON 输出。
4. 关键流程必须可追踪：快照 + 事件 + 报告三件套。
