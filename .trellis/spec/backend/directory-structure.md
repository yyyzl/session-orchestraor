# Directory Structure

> 当前后端以“编排核心 + 适配层 + 持久化层”分层组织。

---

## 目录布局

```text
src/
├── orchestrator/
│   ├── service.py      # 编排主流程、状态机、策略与校验
│   ├── web.py          # HTTP Handler 与路由映射
│   ├── storage.py      # 运行快照/事件/报告持久化
│   ├── runners.py      # Mock/Real 运行器
│   ├── models.py       # 轻量数据模型（dataclass）
│   └── validation.py   # 运行结果一致性校验
├── run_server.py       # 本地服务启动入口
└── codex_app_server_multi_round.py  # JSON-RPC 客户端工具
```

---

## 模块职责约束

- `service.py`：只放“编排决策与流程推进”，不写 HTTP 协议细节。
- `web.py`：只做请求解析、响应编码、异常到状态码映射。
- `storage.py`：统一封装文件读写与并发锁，其他模块禁止直接写 runtime 文件。
- `runners.py`：封装不同执行后端（mock/real），对上层暴露同构 `run_step`。
- `validation.py`：离线校验逻辑独立，不与线上流程强耦合。

---

## 命名约定

- 文件名与函数名：`snake_case`。
- 类名：`PascalCase`（如 `SessionOrchestrator`、`RuntimeStore`）。
- 内部常量：`_UPPER_SNAKE_CASE`（如 `_WINDOW_SWITCH_COMMAND`）。
- 私有工具函数前缀 `_`（如 `_normalize_scope_path`）。

---

## 真实示例

- 分层边界示例：`src/orchestrator/service.py`、`src/orchestrator/web.py`。
- 存储封装示例：`src/orchestrator/storage.py`。
- 启动入口示例：`src/run_server.py`。
