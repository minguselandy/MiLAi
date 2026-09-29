---
status: MECHANICAL_GATE_PASS_REAL_SMOKE_PENDING
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
baseline_source: ec682a3a8b1ac58b41733b882ed0bad367347fed
baseline_report: 1abf5c4d6531db831221d537b96c74fab76383ef
baseline_s0: c6dcd1d7dbca94de4000c8c7aada2cdae49bed61
baseline_s0_merge: 07cc364f96d484ad9ff8497adcf2a6f1b486bdb2
real_generation_calls: 0
real_embedding_calls: 0
product: NO_GO
---

# v6 S1：显式 Request Assembly 的机械等价验收

S1 消除了已序列化 Memory 块的定位、count/replace 和搬运。实际旧请求重放与补充路由差分支持
字节等价工程门槛；这没有产生新的模型效果证据。S3a 的 2–4 个真实 smoke、S2 及后续任务门槛仍未完成。
v5 的 12/12、156/156 继续属于原执行提交，不能改归本次重构。

## 实现与首个断点

Observed：原 hook 先把完整 records 串入 system，project 再搜寻并移到当前 user，router 再按文本
位置替换 query/attention 候选；action catalog 在 provider 的另一个步骤插入。
Expected：placement、routing、capacity 和交付审计共享同一显式结构输入，历史与 checkpoint 保持。

第一解释是局部字符串耦合；第二解释是 hook、provider 与容量路由分阶段装配造成跨层隐式依赖，
只去掉某一次 replace 无法保证最终请求相同。处理同时覆盖三个接线点，没有增加模型规则或控制器。

- `methods/request_context.py` 定义 frozen RequestContext、MemoryPlacement 与纯 renderer，分别携带
  base、boundary protocol、tail、ordinary records、working state、带角色的消息、当前 user 位置及 action protocol。
- hook 在串化前交付组件；仍用同一 renderer 产生原字节的临时 SystemMessage，以保持原 pre-model
  `llm_input_messages`。provider 不从这个字符串解析 Memory，而显式提交完整 action catalog。
- router 用 context.with_records→render_request→capacity.check 选择 all/query/attention，
  完整 catalog 参与每次真实容量检查；没有 serialized-list 兼容搬运分支。
- BOUNDARY_PROTOCOL 按 source role、memory/world、working/maintenance、reply envelope 拆为命名常量，
  拼接字节不变。原 ordinary `{id,value:{content:...}}`、顺序、空 `[]`、分隔符和所有文本保留。
- 原 graph、tool JSON、Store 接口与业务 runner 未改。库默认 `system` 保持，`current_request` 仍显式选择。

## 核对范围与直接证据

[工程检查清单](../data/manifests/next-development-v6-s1-assembly-checks-20260928.json)
记录源码/检查身份和结果；详细本地证据保留在 `artifacts/next-development-v6/s1-checks/`。

| 范围 | 核对结果 |
| --- | --- |
| v5 全部 28 个 terminal jobs | trace、manifest、只读 SQLite checkpoint 哈希绑定 |
| 131 次实际 generation 前 checkpoint | old/new hook→provider→MockTransport，131/131 完整 body 相等 |
| 实际布局 | 66 system、65 current_request；实际路由全部为 all |
| 131 次完整容量检查 | 请求、工具、输出预留和 receipt 相同；Qwen chat-template 字节及 token 序列相同 |
| 原始 graph/tool/pre-model 输入 | raw messages 与 `llm_input_messages` 相同；运行前后 SQLite 文件哈希不变 |
| 86 次公开消息操作审计 | 新旧重算相同，并逐项等于原真实轨迹中的 operation_audit |
| 实际未覆盖的分支 | 两种布局 × 11 条件，共 22 组、26 阶段，完整旧新观测文件相同 |

补充分支包含 empty、all、count/token/capacity 触发 query、attention、空 selection、
noncandidate 容量失败、query 失败、active refs、UPDATE→DELETE 的 attention 续接。
合成容量探针控制分支触发，不能称实际检索压力；它比较完整容量输入，实际 131 条另以锁定 tokenizer
核对真实 token。attention 仍未因任何新真实压力触发。

Root 自建 corpus 指针的 SHA-256：
`dab15b48e76ed681b0e736a1146788db45d7563c20f442ff177c0c49aae34baa`。
131 条有序观测 SHA：`bdaf0ddd027403382b70671c657afa4ef652e32e51fbf3cd396cc5343008a19c`；
86 条审计 SHA：`efd6ab75e5d20973b2e4159746d98423d7919365bad91ecec180cf6bcf60db41`；
22 组路由文件 SHA：`e70972ecb7c2e0c2ae88e4c0a48d06fc2753652efe0c21e18f211076803a06e3`。
Root 独立读取新旧输出并比较，实际文件仅 source_package 路径不同；请求 payload 没有归一化
UUID、正文、时间或 key 顺序。trace 比较仅排除实际运行的 cpu_ns/wall_ns，不排除请求数据。

原 trace 存储的是有序 payload 字典，没有保存原始 socket body。这里证明的是旧/新代码经同一
锁定 HTTPX 编码得到的 body 相等，并等于原 payload 的同编码结果；不声称拥有原 socket 捕获。
MockTransport 返回冻结原响应，不联系 Host、embedding、共享 PostgreSQL 或实际业务世界。

## 必要检查、失败留存与成本

相关 core 与 foundation 检查覆盖 renderer、真实 LangGraph 接线、READ/UPDATE/DELETE、
query 计费、ID-only attention 续接、每消息容量以及历史 C 的同 graph 兼容。
仅运行受影响的类型、格式、矩阵和包边界检查；具体命令/环境/退出码见清单。
没有整套 benchmark、全量测试、build、模型资产下载、部署或 vLLM 参数变更。

离线准备初次失败均保留：Root corpus helper 曾尝试使用此锁定 JsonPlusSerializer 不支持的
allowed_objects 构造参数，TypeError 发生在读取 checkpoint 前；改用该环境的原默认构造。
Sol 初次窄测遗漏 PYTHONPATH 导致 collection 失败，以及局部 Ruff enum/未用变量诊断，均收敛后再通过。
旧源码首次重放已通过首条 payload/capacity，但 helper 漏掉 Trace 的 stage/role 包装，补齐同一包装后重放；
未修改实际请求或基线源码来回避差异。
这些是工程准备错误，不是模型语义失败，也不是清零或隐去真实请求的理由。

连续账本保持 **3,125 generation calls /3,971,354 generation tokens /22,221 embedding tokens**，
SHA `98b02945ab195ad94e37061f97c5ba5eb8068ecd87ff47caef9f76f9e51fdd15`。
全部重放为本地 mock；开发代理费用与实验账本分开，旧 v5 费用未重记、未清零。

## Reflection 与下一步

1. 支持：显式装配能在实际跨层调用链上保留旧行为字节，而不依赖 Memory 文本唯一出现。
2. 反驳：必须保留字符串搬运才能兼容原 layout 的工程假设。
3. 首断点：序列化之后才依据文本位置修改 Memory carrier，并以同样方式路由。
4. 简单解释：已有方法行为未变，当前证据是结构改善，不是新语义能力。
5. 简单方法：一个纯数据/render 模块加现有 view/router 接线即可，无需更多服务或持久层。
6. 复杂度：一个共享 RequestContext；没有新增 controller、模型调用或长期事实副本。
7. 过拟合：全实际131条与未出现的路由分支降低模板遗漏风险，但不能证明未执行语义任务稳定。
8. 反例：empty、active refs、tool continuation、UPDATE/DELETE、base 超容量及 system 默认均已机械覆盖；
   后续真实 smoke 和 S4 还要核对 current/history/world/temporary 与命令式引用。
9. Continue：先独立发布本次源码与证据，再做 S2 离线 Model/Audit 组件计量。
10. 理由：S1 等价门槛有直接证据，尚无依据在此阶段改 prompt、删语义或宣布完整 v6 已完成。

后续 S2 仅可移除不影响任务语义且可从 trace 恢复的信息；10%–20% 目标不是强制删数据的许可。
若改 Model View，仍须完整 12-script/156-obligation 暴露回归；S4 新任务不能用旧回归替代。
