# Quality Guidelines

> 以“可追踪、可测试、可恢复”为核心质量目标。

---

## Overview

- 后端改动必须覆盖对应的单元测试或集成测试。
- 关键流程需具备事件记录，便于回放与审计。
- 输入参数必须显式校验，禁止“隐式容错吞错”。

---

## Forbidden Patterns

- 禁止在业务流程中静默吞异常（`except: pass`）。
- 禁止绕过 `RuntimeStore` 直接写 `runtime` 文件。
- 禁止字符串拼接路径并跨目录写入（需 `Path.resolve()` + 范围校验）。
- 禁止在 HTTP 层返回非 JSON 错误体。

---

## Required Patterns

- 公共入参在入口校验并抛明确异常类型。
- 文件写操作必须 UTF-8 编码，结构化数据必须 JSON 序列化。
- 并发读写必须使用锁（当前为 `threading.Lock`）。
- 对外 API 必须保持字段稳定，新增字段优先增量扩展。

---

## Testing Requirements

- 对编排主流程：覆盖正常流、失败流、重试流、窗口切换流。
- 对 Web 服务：至少覆盖静态资源挂载与基础 API 可达性。
- 对 runner mock：覆盖核心页面产物与关键交互逻辑。
- 测试入口以 `tests/` 下 `unittest` 为主，保持可在本地快速执行。

---

## Code Review Checklist

- 是否保持分层：`service` 不混入 HTTP 细节，`web` 不承载编排决策。
- 是否新增了事件字段？若有，`validation.py` 是否同步。
- 异常映射是否正确（400/404/409/500）。
- 改动是否附带测试更新，且断言覆盖关键行为。

---

## 真实示例

- 编排流程与参数校验：`src/orchestrator/service.py`
- Web 映射与静态资源访问：`src/orchestrator/web.py`
- 测试覆盖样例：`tests/test_workflow_control.py`、`tests/test_web_static_mount.py`
