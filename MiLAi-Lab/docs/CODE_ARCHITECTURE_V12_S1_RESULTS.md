# v12 S1：公共合同与请求呈现

S1 已完成本地工程验证，尚不代表 v12 全部完成或 GitHub CI 已通过。
基线源码为 `cca2fd9`；前置文档提交为 `19339bff`。语义实验保持暂停。

`RequestContext`、`MemoryPlacement`、`ModelView` 的唯一实现进入 `contracts/request.py`，
记忆材料和 JSON-action 历史渲染进入 `memory/presentation.py`。
旧 `methods/request_context.py` 只 re-export 相同对象，调用方转向 canonical 路径。
`contracts/memory.py`、`contracts/operations.py` 描述已有字典和状态的数据类型，
没有新增序列化、持久化、权限或语义判断。

当前 Foundation/B1/M1/ODR/freshness 身份检查纳入实际 canonical 文件，
保留历史锁；新增源码登记与包内文件一致性、遗漏和篡改检查。
Foundation 依赖的 identity 检查显式进入对应 CI 组，其余合同检查保持 Core 可用。

| 证据 | 本地结果 |
|---|---|
| 迁移前后定义 AST | 7 个定义一致 |
| 冻结请求呈现 | 16 个请求及 4 类错误保持一致；输入副本未改变 |
| 定向行为与结构检查 | 102 passed，2 warnings |
| Ruff / Core mypy / 相关 Foundation mypy | 通过；Core mypy 覆盖 31 个源文件 |
| boundary / tools boundary / verification matrix | 通过 |
| sdist → wheel → 无依赖隔离安装 | canonical 文件字节核对、兼容导入及 16 个安装包渲染重放通过 |

首次 Ruff 检查发现导入排序问题，首次新增 AST 检查存在断言问题；均保留原记录并修正，
后续相关检查通过。没有将失败日志删除或把初次检查改记为通过。

sdist SHA256：`d633c308dbf8ca51f55bee4d1109017d4b1edc35e65e8bdf215e1b35a5162cbb`。
从该 sdist 构建的 wheel SHA256：`1370b8d8242a6969ae345fb7225d4c4be4e211da1c429154b9079d4d3d28f656`。
这些是此次本地构建产物的身份，不承诺包含时间元数据的后续构建字节完全相同。
构建只使用现有缓存；未下载依赖，未调用 Host、embedding 或 Judge。

本阶段只证明请求合同提取的兼容性。MCP/CRUD/Store、外部 SDK、完整 JSON/native HTTP、
容量及 benchmark 持久制品的独立冻结和迁移验证仍待 S2–S7 完成。
总体验收见[执行记录](CODE_ARCHITECTURE_V12_EXECUTION.md)和
[验收矩阵](../data/manifests/code-architecture-v12-acceptance.json)。
