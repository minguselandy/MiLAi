# MiLAi：第一批代码轻量化与结构审查

日期：2026-09-27。基线：`9515017a5dfaba6b6e306fa778fd20f4383b6e35`。
范围：Lab 的 Local State–Attention 控制器、协议与离线测试。

用户本次明确要求分析仓库并先实施轻量化。本批仅执行代码重构和离线验证；不恢复原研究
Goal，不运行 D1–D6、模型实验、embedding、数据库业务动作或部署。不改 Product、Archive、
旧报告、数据、rubric、配置、锁文件、默认方法和失败账本。State–Attention 仍是研究候选。

## 1. 判断与范围

不是没有使用成熟框架。当前入口已经复用 LangGraph/LangMem 的公开 hook、消息、Store 和
checkpoint。需要先减轻的是其上的重复协议表达、混合职责与不必要的局部计算，而不是重写
Agent runtime 或换数据库。根 `SOURCE_OF_TRUTH.md`、`REPO_MAP.md` 和两级 `AGENTS.md`
规定的 Product/Lab/Archive 依赖方向保持不变。

本批精读了当前 controller、bank 的来源/读取部分、已有 integration、CLI 装配与冻结入口、
测试入口、依赖配置和 CI；历史报告只用于理解故障背景。没有逐文件审计所有历史算法、
Product、Archive，也没有把 2026-09-24/25 的 contextual 实验结论冒充当前 LSA 结果。

当前执行环境无法直接 clone 或下载完整仓库，且没有锁定的 LangGraph/LangMem 环境。
因此通过 GitHub 接口读取源码，建立选定文件的本地工作副本；修改前 controller 的 Git blob
SHA 已逐字节核对为 `93a6dfddebd7f50e7d6321c3337489f31511f789`。测试所需的未修改依赖
`contextual_artifacts.py`、`contracts/arms.py` 和包 `__init__.py` 也与远端 blob 一致。
本批验证不是完整锁定环境下的全仓回归，不能以本地通过替代合并前 CI。

## 2. 当前结构中需要分开的职责

| 位置 | 观察 | 本批处理 |
| --- | --- | --- |
| `local_state_attention/controller.py` | 同时包含提示词改写、schema、响应解析、预算和 U/维护/A 编排 | 提取纯协议，保留执行次序与错误分支 |
| `_maintenance_prompt` | 通过多次 replace/index 删除另一份 prompt 中的片段，维护时容易错删或遗漏 | 改为按明确片段组合，所有已支持变体的文本保持原样 |
| update/read selector | 两份相似 schema 和 ID 校验，容易在空集、重复 ID 上漂移 | 共用纯函数，仍拒绝无效返回，不自动纠正 |
| 候选过滤 | 每个 State 都重新构造 `set(update_ids)` | 提前构造一次，保留 bank 顺序 |
| combined/staged 调用 | 容量读取、占用和落盘逻辑重复 | 一个 `_reserve_call`；保留各调用原本的错误回执 |
| 响应解析 | combined/staged 两次实现相同 JSON 及 finish_reason 解析 | 单一解析器，combined 再检查 edits/focus |
| Controller 导入 | bank/provider 只用于类型标注，却在导入时加载可选依赖 | 改为 TYPE_CHECKING 导入，类型声明不变 |
| 现有 LSA 单测 | 文件级 `importorskip("langmem")` 会一起跳过纯协议检查 | 新增不依赖可选框架的合同测试；原集成测试保留 |
| `bank.py` | pending 依赖 events 全扫描；states 与事件写入也有扫描 | 记录为后续测量点，本批不改存储/并发语义 |
| `integration.py` | 保留原 checkpoint，同时交付模型维护的 State | 不在结构重构中改变证据可见性或旧助手历史 |
| CLI `SOURCE_PATHS` | 已按 src 下全部 Python 文件生成身份清单 | 新协议文件会被既有冻结逻辑捕获，无需改旧 manifest |

目前不能根据文件大小断言深拷贝、数据库或 Python CPU 是真实推理成本主因。也不能将
扫描减少、模型输入减少或准确率改善三者混为一谈。

## 3. 实际代码变化

新增 `src/milai_lab/methods/local_state_attention/protocol.py`，只依赖标准库，负责：

- 组合现有提示文本，而非先生成一段自然语言再用字符串替换决定其语义；
- combined 和 selector schema；
- 状态、目录、事件的模型可见字段投影；
- JSON/finish_reason 解析和 selector ID 集合校验。

`controller.py` 继续负责状态生命周期、调用容量、请求角色、U/维护/A 顺序、提交和 trace。
没有新增管理服务、状态库、语义审核器、重试层或学习策略。没有删去多 State 或完整记忆
操作的研究目标。原来的 `control_schema`、`ControlResponseError` 和解析静态方法入口保留。
私有的字符串手术函数 `_maintenance_prompt` 不再保留；内部调用改为直接组合维护提示。

已落实的一项局部算法优化是：候选过滤不再对每行构造更新集合。若 bank 有 N 个对象、
U 有 K 个 ID，原来的重复集合构造有 O(NK) 工作；现在构造一次后过滤，通常为 O(N+K)。
这是 Python 局部计算量的分析，不是测得的端到端加速或 token 节省。选集、候选顺序及
schema enum 顺序不变，也没有省略任何 Store 调用或模型请求。

控制器从 512 行变为 372 行；新增协议模块 211 行。两文件合计 583 行，较原文件多 71 行；
UTF-8 字节从 29,116 变为 28,696。不能把控制器减少 140 行写成全仓减少 27%。本批价值
是拆开测试和变更边界、消除重复逻辑及隐式依赖，不是以代码行数制造“瘦身”成绩。

## 4. 保持的执行合同

模型可见 prompt、JSON 请求、字段顺序、候选顺序、权限/来源检查、A/U 区分、
`pre_model`/`turn_end` 默认值、预算及调用次序不变。未改变自定义 Host 或底层 LangMem
的普通 memory 行为，也未把已知的错误 UUID upsert、语义重复应用或精确对象 key 问题
包装成已经修好。

空读集合仍然有效；未知/重复/非字符串选择仍被拒绝。工具或模型基础设施错误不被改成
成功，无效请求不被静默修补。部分提交与 pending 继续交给原 bank 管理。精确重试的隐藏
身份、同文本不同事件、删除传播和快照恢复代码均未修改。

历史结果继续属于其各自冻结源码；即使协议保持等价，也不能说新源码已重跑历史16轮。
后续真实运行必须使用新的源码身份与 namespace，不续写旧分数或账本条目。

## 5. 实际验证与限制

本地 Python 3.13.5、pytest 9.0.2、httpx 0.28.1、jsonschema 4.26.0 环境。
其中 pytest 不在仓库 dev 声明的 `<9` 范围；本轮不是锁定环境验证。未安装或修改用户原环境。运行命令：

```bash
PYTHONPATH=src python -m pytest tests/unit/test_lsa_controller_contract.py -q
```

结果：**71 passed**。全部使用合成协议 fixture 和内存 Bank/model doubles，无真实模型、
embedding、LangGraph checkpoint、外部数据库或业务动作。新增 fixture 不属于 benchmark。

另做旧/新控制器的 **35 个完整离线流程差分比较，0 个差异**，比较完整请求文本和 schema、
请求角色与 stage、模型调用序列、Bank 调用、apply 参数、回执、pending、容量文件及 trace。
场景包括 combined/global/local、维护-only、LR/LRU、空 bank、空 edit、缓存、partial、
close、容量拒绝、selector 错误、截断、JSON 错误、timeout 和不可吞掉的 I/O 错误。
这些不是 35 个真实用户任务，也不证明持久化或模型语义正确。

为在无可选框架环境中比较旧实现，差分加载只去掉了旧文件两个仅用于类型标注的
bank/provider 导入；函数体和控制逻辑未改。新实现直接导入，不使用同样的替换。
测试中的 golden digest 由基线控制器生成，不由新实现反向生成预期答案。
此外，**12 个提示变体逐字相同**，包含 local/global、局部粒度开关和维护候选模式。

已运行：上述单测、字节身份核对、修改文件语法编译及定向依赖边界检查。
未运行：锁定依赖环境的原 LSA/LangMem 集成套件、全仓 pytest、Ruff、Mypy、包构建、
真实 HTTP、数据库/恢复故障注入以及任何 benchmark。Ruff 离线缓存不可用，未以其他
检查冒充 Ruff 通过。合并前应继续使用仓库已有 fast CI，包括 optional foundation gate。

## 6. 仍然需要算法实验，而不是结构重构的问题

| 问题 | 当前解释边界 | 下一最小检验 |
| --- | --- | --- |
| State 与普通 memory 同时维护同一事项 | 可能是双写责任不清；不等于多 State 本身错误 | 保持完整 CRUD，单独比较写入责任，不能靠删除 baseline 能力获胜 |
| 正确 State 后实际动作仍错 | 时间、旧答案和回执中的提案相互竞争；尚无唯一根因 | 固定合法前缀逐项干预，保持实际工具和 strict 评分 |
| U/A 三段控制成本 | 多一个模型选择器不自动意味着更稀疏或更便宜 | 固定 bank/前态与预算，比较普通检索与 selector |
| 综合卡丢失未改内容 | 局部 State 仍可能包含多个事项，且正文整体重写 | E1 保持测试与真实变化反例；不继续只加提示 |
| 缺少真正严格的更新目标语义 | 上游 update 可能采用 put/upsert 合同 | 先核对锁定依赖；若要行为变更，独立 PR 与控制 |

这些项目没有在本批静默实现。新算法的收益必须有独立对照，而不能从本次等价测试推导。

## 7. 后续代码组织建议

先保持 `protocol -> controller -> bank/integration` 的职责边界，不增加统一平台。
将模型可见内容的修改放在协议模块，将副作用和时序修改放在 controller/bank，将
端到端评分留在 runner/scorer。配置候选仍通过既有入口切换。

之后优先检查实验 CLI 的装配/汇总边界及 AGENTS 中历史过程记录的体积，但本批不迁移
或删除它们。完整仓库瘦身需要覆盖真实引用和恢复要求，不能凭名字相似批量清理文件。

本批是第一阶段代码整理，不是全研究完成、不改变 Product NO-GO，也不是 State–Attention
有效性的证明。远端交付使用独立分支/PR；基线提交是撤回本批修改的明确参照，不直接合并 main。
