# Lab 依赖边界

规则来源是 [v12 计划](MILAI_CODE_ORGANIZATION_BOUNDARY_PLAN_20260929_v12.0.md)。
当前实施和门禁证据见[执行记录](CODE_ARCHITECTURE_V12_EXECUTION.md)；本文不把目标规则当作已经通过的检查。

| 层 | 允许的主要依赖 | 禁止的上层依赖 |
|---|---|---|
| contracts | 标准库、typing、轻量 DTO | 业务实现、模型、方法、runner、外部 SDK |
| application | contracts、本地持久化、必要 LangGraph 适配 | runner、研究方法、scorer、外部记忆 SDK |
| memory | contracts、Store、LangMem 适配 | runner、benchmark、业务世界、具体研究方法 |
| providers | contracts、通用计账、HTTP/模型 SDK | 具体方法、runner、benchmark |
| integrations | contracts、providers、memory、外部 SDK | runner、scorer、方法策略 |
| methods | contracts、memory/application 接口、通用 provider hooks | runner、benchmark scorer、Product 私有实现 |
| benchmarks | contracts、datasets、scorers、integrations、harness | 方法实现的重复副本 |
| runners | 下层能力的显式组合 | 不应成为非 runner 共用能力的唯一 owner |

函数内导入和 `TYPE_CHECKING` 同样属于依赖。不能用动态导入、全局注册或泛化命名隐藏反向依赖。
历史同层模块循环与跨层反向依赖分开记录，不借此启动全部历史方法重构。

兼容 facade 只允许文档字符串、导入/re-export、`__all__` 和必要的 `TYPE_CHECKING`。
同名包装函数、重复实现和带分支的兼容构造器不等于纯 re-export。
旧路径与 canonical 路径必须指向同一对象；具体方法的构造迁移见
[Provider 决定](CODE_ARCHITECTURE_V12_PROVIDER_DECISION.md)。

Core 导入不加载 LangMem、PostgreSQL、Mem0、SimpleMem 或本地模型资产。
Foundation、External 和 Local-artifact 检查按真实依赖执行；缺失依赖不能靠扩大 skip 制造通过。
源码移动必须同时更新当前 identity 和验证矩阵，并验证 sdist/wheel 及安装后导入。
历史 source lock 不随迁移重写。

## 公共制品 IO 的实际归属

S3 将原 `harness.contextual_artifacts` 中的 `digest`、`read_json`、`write_json`
提取到只依赖标准库的 `harness.artifact_io`；旧入口导出相同对象。它们处理全 Lab 的 JSON
制品，不属于记忆策略，因此不放进 `memory`。Integration 允许依赖这一明确的底层 IO 模块，
不因此允许依赖其它 harness 编排、runner、method 或 scorer。自动边界必须验证该叶子模块
本身没有上层依赖，且集成只使用这一公共 IO 能力。

这是对计划职责图中未展开的公共设施节点的具体化；原 JSON 字节、排序、摘要和临时文件
替换行为仍须保持。应用 journal 的旧公共入口无需随之全仓改写。
