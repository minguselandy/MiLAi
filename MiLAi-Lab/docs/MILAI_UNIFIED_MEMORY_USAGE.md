# 统一记忆功能候选：入口与实际状态

本轮按[多Agent任务卡](MILAI_MULTI_AGENT_DEVELOPMENT_TASKS.md)及用户提供的
[配套规划](MILAI_UNIFIED_MEMORY_ARCHITECTURE_AND_BUILD_PLAN.md)开发。
五个模块已合流到同一MemoryService，父版本为`5c36b28`；本提交加入中央Host、
benchmark、配置及显式整理／完整请求恢复入口。它是待测功能候选，尚无本候选的
真实模型效果、最终方法选择或Product准入。原[build-first完整任务](
MILAI_BUILD_FIRST_DEVELOPMENT_AND_EXPERIMENT_PLAN.md)继续有效。

## 实现及证据边界

| 能力 | 正常实现／入口 | 当前证据 |
|---|---|---|
| 来源与Episode | 同Store保存原始来源和引用索引；实际维护提交后的描述保留来源、角色和解释属性 | 真实SQLite、重开和遗忘示例；没有真实模型效果结论 |
| 时间与范围修订 | 既有I2编辑器及只读关系视图；实际角色／报告／捕获／提交时间由程序填写 | 一般规则、例外、共同条件、撤销、历史和整体数量工程示例 |
| 实际对象与恢复 | 普通Host采用应用适配器；lookup／execute／observe／discover共用原业务journal | 两个沙箱、未知发现、原操作核对及当前权限检查；不是外部系统exactly-once |
| 共同维护 | 两种recipe和Append-only；真实容量预览、原文分批、实际提交后刷新当前视图 | Host与benchmark既有检查；分批调用分别保存原输入和首次响应 |
| 激活与用途 | 同Store记录实际使用／显式反馈；独立于真实性、权限和删除 | 24步隔离轨迹、5次脚本编辑、0HTTP；用途估计尚未校准 |
| 显式整理／继续 | `run_memory_operations.py`打开普通Host的同一owner bank、配置、队列和成本账本 | 普通Host部分预订→重开只读→只补标签→维护实际结果→整理的脚本传输检查 |

源文件、示例与接口分工见[一页接口约定](MILAI_UNIFIED_IMPLEMENTATION.md)。
脚本响应检查使用真实SQLite和实际沙箱副作用，但不会验证自然语言理解质量。
一个执行COMPLETED、一个提交回执和一次正确回答分别报告，不能合并成语义通过。
Root的11项集中接线检查、相关Ruff／mypy及包／工具依赖边界通过；分批汇总按实际叶批次
计数，父容器重复的回执不再重复相加。旧无效标签、失败和固定产物保持。
改动仅在Lab：增加可选来源／时间字段、profile及公共操作入口，沿用实际owner、版本、
可见性和当前许可。未改Product Schema/API/Canonical。源码回滚基线为723ceca，
不是预算或已发生业务效果回滚；远端发布和新源码CI分别记录。

## 普通Host

在Lab目录运行；`PYTHONPATH=src`。Python仍使用原Lab虚拟环境。
实际模型执行由Root串行安排，先冻结候选版本，再使用新产物目录。

```bash
python tools/run_functional.py prepare --root artifacts/unified/host-v1 \
  --config configs/milai-unified-functional-v1.json --source-version ACTUAL_SOURCE_COMMIT
python tools/run_functional.py message --root artifacts/unified/host-v1 \
  --owner example-owner --session ordinary --message-id first \
  --text '请记住我现在的安排。' --occurred-at 2026-10-07T06:00:00Z
python tools/run_functional.py episodes --root artifacts/unified/host-v1 --owner example-owner
python tools/run_functional.py activation --root artifacts/unified/host-v1 --owner example-owner
python tools/run_functional.py export --root artifacts/unified/host-v1 --owner example-owner
```

公开配置是`unified_v1`、M、I2、六项EditFeatures及extract-then-edit，保持既有
Qwen3.6、BGE-m3、dense K10及容量。`answer_from_delivered_v1`只在实际读取额度耗尽后
停用额外读取，让Host用已送达材料作答或说明缺失；业务能力继续服从当前许可。
独立对象／版本／范围／游标的读取进展可由适配器`read_progress`检查。
没有扩读取次数、输出预算或并发额度。

## 显式整理及语义继续

```bash
python tools/run_memory_operations.py --root artifacts/unified/host-v1 \
  --owner example-owner --session ordinary --request-id organize-1 \
  --text '整理这些已保存的经历。' --episode-id ACTUAL_EPISODE_ID
```

不指定Episode／事项时最多选择20个可见、未整理Episode；可用`--record-id`指定实际事项。
整理回放不重新捕获旧原文、不产生独立支持或用途标签，也不执行业务。
旧请求未确认时保留原状态。继续时使用新的当前命令ID、完全相同的旧Episode／事项选择、
`--prior-request-id`和明确`--new-attempt-id`；没有新尝试ID只核对旧结果。
旧语义提案可能已提交时先查原操作回执，未能确认不得另写。

## 完整请求恢复

`--operation resume`调用同一应用适配器及既有请求进展journal。第一次给出实际用户任务的
可信`--requirements`文件，后续以`--resume-request-id`找到它；不是从记忆、gold或未来评价
推导业务权限。计划包含`target`、`steps`、`save_result`、`feedback`；每一步声明操作、
实际参数、完成所需的字面状态字段，可用`arguments_from_state`从实际查询取对象ID。

```bash
python tools/run_memory_operations.py --root artifacts/unified/host-v1 \
  --owner example-owner --session ordinary --request-id inspect-1 \
  --text '只查看当前完成情况，不执行也不保存。' \
  --operation resume --resume-request-id original-request --readonly \
  --requirements artifacts/unified/actual-request.json
python tools/run_memory_operations.py --root artifacts/unified/host-v1 \
  --owner example-owner --session ordinary --request-id continue-1 \
  --text '继续尚未完成的标签，并保存实际结果。' \
  --operation resume --resume-request-id original-request --allow-operation complete_label
```

每次先发现实际对象状态；已确认效果保持，只执行当前允许的剩余步骤。
`--no-save`、`--readonly`、`--no-read`分别限制当前保存、mutation与读取。
语义保存调用相同共同维护器，以实际工具来源为证据；业务完成不自动表示记忆完成。
旧模型未知／已确认未提交需要新的命令及明确新尝试；旧提交未知必须先核对原操作。
同一当前命令ID再次调用只观察／核对；要继续产生效果必须发出新当前命令ID。

反馈回执表示结果已经写入本地输出文件，明确`host_seen: false`；不声称用户已看到。
最终JSON分别包含业务、记忆、反馈进度。首次命令结果、后续观察和各次失败分别保留。
document工作流使用同一合同，需按当前许可提供实际审批／发布操作和精确版本。

## 激活、反馈和模拟

统一候选公开配置保持`memory_ranking: dense`作为共同底座。显式配置`activation`时，
排名为归一化cosine加`0.1 × sigmoid(activation)`；用途权重默认0。纯排名API先过滤
可见性／权限，保留调用方明确给出的置顶／未完成保护项。没有从自然语言猜保护或权限。
时间衰减使用秒，tau=86400、decay=0.5、epsilon=1e-6；90天冷存储建议从不授权删除。

普通Host只在包含实际Reader材料的请求获得响应后记录使用；benchmark只记录实际
Reader响应，缓存重开和gold诊断检索不增加使用。每事项／当前请求最多一次。
用途反馈用`ActivationIndex.record_feedback`显式传入可见user／tool原来源、反馈协议和
useful标签；unknown不作负例，Assistant自述和内部回放不作反馈。Beta(1,1)估计输出
样本量及未校准用途均值，`factual_probability`始终为null。

```bash
python tools/example_unified_activation.py
python tools/example_unified_revision.py
python tools/example_unified_maintenance.py
python tools/example_unified_recovery.py
python tools/example_unified_episodes.py
```

隔离模拟入口调用公共ingest／maintain／recall／consolidate／resume／forget，使用独立owner、
临时SQLite、虚拟时钟和真实沙箱；只把当前事件传给运行回调，未来事件与评价断言不进
运行材料。24步例子包括间隔、取用、更正、例外／撤销、整理、部分执行和遗忘重开。
脚本传输只证明机械接线，B的时间／关系示例另验证具体投影，不能冒充真实模型成绩。

## 迁移、导出与清理

`index-episodes`为已有可见来源建立同Store索引，不改原文／旧时间、不增加来源或HTTP。
启用新profile须使用新的准备目录和明确配置版本；已有冻结运行不改配置或热换源码。
导出包含当前可见来源、记录、允许的历史和全部可见Episode；不导出业务journal作为记忆事实，
也不把导出当权限凭证。现有`forget`继续撤销来源／事项访问，相关Episode、激活和整理输入
随原可见性不可用。`disable`只是关闭入口，不删除持久数据；清理只能处理明确指定的独立
临时／开发bank，不能删除旧实验或其他owner数据。未承诺物理擦除或跨系统事务。

## 2026-10-07 06:33 UTC固定观察

新候选真实generation／embedding／Judge均为0。原dffc232评分PID已不存在，只有
18/32评估闭合（8／8／2／0）及396个确认Judge响应；request397只有request.json，
没有响应／错误／评分终态，退出原因未知，未重启或重发。第二用户原作者更新12/15
（valid12）、QA8/12（valid12）；无效标签保留，不能据部分结果排名。

连续账本未变：41,669请求，generation known161,550,781／charged161,742,269，
embedding1,120,458，unknown5=历史4+旧未确认397。没有重置或新增上限。
723ceca仍是本次远端读取的PR头，其自身Fast／Full成功；本地新增源码的CI另核对。
04:29已提交报告、旧源码830d23a、实际dffc232预测／评分及本轮候选分别记录。

后续先固定本提交自身版本和必要检查，执行统一五条真实冒烟，按最早语义断点改进，
再集中predict／score。原同前态recipe、五方法、65／277、native／drift／消融／紧预算、
16未读保留用户、外部和Host135／192＋冻结后新故事及六项最终交付均仍未完成。
Product仍为NO_GO；PR #85保持draft，不合并。
