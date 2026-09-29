# v12 S3：外部记忆集成归属

状态：本地工程验证完成，远端 CI 与发布待完成。
源码基线为 `379ad45eab3fc40798534bd7a73e7a1245918bc9`。

Mem0/SimpleMem 原生适配器的 canonical owner 分别是 `integrations/memory/mem0.py` 和
`integrations/memory/simplemem.py`；旧 runner 保留纯 re-export。SDK 配置、数据库、
add/search/snapshot、原生重试及 provider 参数属于集成；任务顺序、作用域选择和资源打开时机仍由 runner 组装。

Mem0 的版本身份校验原来位于 baseline，随其原实现下沉。共用的
`digest/read_json/write_json` 则进入标准库制品 IO 模块，保留原 harness 导出；
这项职责决定见[依赖规则](DEPENDENCY_RULES.md)，不是新的记忆存储平台。

## 迁移前证据

两个捕获均调用现有真实 SDK，使用 MockHTTP 模型出口和临时本地数据库。
测试固定 UUID/时钟/睡眠，并将临时根路径表示为 `<TMP>`；未改变 SDK 源码、原策略或模型参数。
MockHTTP 中的 generation/embedding 计数属于临时测试账本，不计作真实实验调用。

| 组件 | 保留身份 | 冻结合同 |
|---|---|---|
| Mem0 | 2.1.0；原 pin `f8082a7345dadd9e042ebbc40b57b1498c8f6d63` | config/policy/wire/预算、Qdrant 持久 ID 与重开、owner scope、超时、pending 重复拒绝、provider/embedding 错误 |
| SimpleMem | 原 pin `db80b6a7c591e0ea730a058e9f5fc4eb06572299` | policy/wire/预算、LanceDB 持久 ID 与重开、合法空结果、原生重试和解析恢复、耗尽、容量错误、查询降级与插入错误 |

[Mem0 golden](../data/diagnostics/code-architecture-v12/mem0-contract-golden.json)：621,310 bytes，
SHA256 `b042b559f8cd73620e530bf1168ff591cebe38a7a763d507a1d9a97d8db69518`。
[SimpleMem golden](../data/diagnostics/code-architecture-v12/simplemem-contract-golden.json)：650,215 bytes，
SHA256 `755e77811bb1d7089970da283498b79630c2e951847983df3d326509e72cef43`。
文件包含实际 SDK 源码哈希和合成完整调用合同，不包含模型权重、数据库或私密运行轨迹。

本地真实 SDK 重放复用了原环境、Mem0 的已有缓存和 SimpleMem 的 pinned 源码；
这些资产依赖与无资产的公开合同检查分别报告。不能将本地通过解释为所有公开 CI 环境都具备这些资产。

首次迁移后完整比较未通过：Mem0 的 12 个、SimpleMem 的 36 个 `events[*].wall_seconds`
不同，其余已比较字段一致。捕获 fixture 固定了纳秒计时函数，却漏固定 provider 使用的
`time.monotonic()`。首次补充尝试误固定了 `perf_counter()`，因此比较仍失败；
核对 provider 源码后纠正测试时钟选择，该次失败也保留。原 before、失败 after 和上述公开 golden 均保留，不用删除耗时字段
或改变运行时计时来修复检查。

竞争解释为迁移改变了真实调用链，或 fixture 遗漏了非确定性时钟。逐字段比较显示调用、
回执、预算和存储内容保持，差异只在 elapsed time；实际 provider 使用的时钟也未固定，
因此先修复测试条件，再由独立旧/新重放验证，未据此调整 SDK 策略。

后续补充检查从冻结的完整旧源码和旧测试重放基线，并只在 fixture 固定漏掉的时钟；
补充 before/after 使用独立文件，并核对旧模块来自冻结副本、迁移后模块来自当前源码。
补齐时钟后，两组完整 before/after 文件逐字节相同，包含所有 `wall_seconds` 字段。

补齐时钟的独立基线已生成，Root 对 Mem0 的 38 个、SimpleMem 的 77 个加载模块逐项核对了
冻结副本来源和迁移前源码哈希。严格重放使用以下补充 fixture，原始 golden 不覆盖：

- [Mem0 确定性合同](../data/diagnostics/code-architecture-v12/mem0-contract-deterministic-golden.json)，
  SHA256 `faacff1e0c5741522d5cc80b85374f7e6e87b4de6ce68ec849d76b8d78b8869d`。
- [SimpleMem 确定性合同](../data/diagnostics/code-architecture-v12/simplemem-contract-deterministic-golden.json)，
  SHA256 `e6ebdeccd5c0334ff60ffd0c5cffb769b45e8d1e153d5cd57e22e47091705338`。

## 最终本地工程检查

- Mem0 相关 7 项、SimpleMem 相关 13 项、可移植接口 8 项、源码/身份结构检查 17 项通过，共 45 项。
- Ruff、Core/Discovery/External mypy（33/148/5 个源文件）、两项 boundary、verification matrix 通过。
  Ruff 的覆盖限制在 S4 发现：最后调整确定性 fixture 文件名后，只重查了 probe 文件，遗漏
  `test_simplemem_contracts.py` 的一行超长字符串；因此 S3 的全量 Ruff 通过不覆盖这次最后的文件名调整。
  S4 以纯换行修复并重新检查，行为与 SDK 重放结果不受影响。
- 离线 sdist → wheel、新无依赖 Core 安装检查通过；Mem0/SimpleMem 分别借用已有依赖目录，
  从解包 sdist 的 helper/fixture 完整重放，所有加载的项目模块均验证来自新安装目录。

sdist SHA256：`59574e986fb1b05b25370d0dcc2a73529ebe58008a5d0676a088db4f4f029217`。
wheel SHA256：`f34212dfe752d3dc50d691694f82caa363ab79c8d99877f8ceeb70750fdae535`。
它们标识本次构建产物，不承诺后续独立构建的时间元数据完全一致。

原始捕获与两次时钟相关比较失败均保留；其余初次检查记录见[精简工程证据](../data/diagnostics/code-architecture-v12/s3-engineering-evidence.json)。
远端 CI 尚待最终集成，不能由本地通过代替。
它们只能证明工程行为保持，不能推导记忆质量、任务成功率或成本收益。
