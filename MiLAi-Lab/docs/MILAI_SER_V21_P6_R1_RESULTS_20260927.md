# P6 R1：八例通过，current冲突暴露来源权威问题

状态：`FAIL_REFLECT_AND_CONTINUE`。九个预先冻结的新实例8/9通过；唯一失败是current_conflict。连同已明确引用的两条P5 R2 A5 v2和一条P5 R1 irrelevant A5 v1，同一冻结算法有11/12类型覆盖通过；不是全新统一合同的独立12例试验，也不抹去P5 R1四个失败。

| 本轮实例 | 最终结果 | exact get | 回复降权 | 更新后search |
| --- | --- | ---: | ---: | ---: |
| categorical_route | South，PASS | 3 | 3 | 0 |
| boolean_approved | true，PASS | 3 | 3 | 0 |
| boolean_cancelled | false，PASS | 3 | 3 | 0 |
| deleted_evidence | 无业务动作，请求当前依据，PASS | 0 | 2 | 0 |
| multi_revision | X@2后X@3，实际West，PASS | 3 | 5 | 0 |
| current_conflict | 越过冲突实际记录West，FAIL | 0 | 0 | 0 |
| assistant_only_stale | 自然新search后South，PASS | 0 | 4 | 1 |
| no_stale | Central，无额外干预，PASS | 0 | 0 | 0 |
| mixed_memories | 四种状态真实同现，South，PASS | 0 | 3 | 0 |

CURRENT与UNKNOWN原始项、item顺序及checkpoint原历史保持；stale/deleted历史正文正确隔离。混合例的UNKNOWN来自公开工具在观测范围外的真实创建，未伪造revision。23次机械demotion均符合实际生成snapshot的risk，precision/recall合计23/23；无变化/冲突例各0/0，不写成完美precision。这里没有逐词语义因果推断。

Root读取了删除、冲突和assistant-only完整回答与动作。删除明确缺少当前warehouse并拒绝记录。assistant-only本轮在第二条公开消息实际search后回答South，没有复现P4中间虚称搜索；这不抹去P4缺陷。冲突例还在已执行业务后说“pending approval”，是额外的执行状态表述错误，原文保留。

## Failure Review

Observed failure：Alpha/East与Beta/West两个CURRENT正文都到达实际请求；两正文均写未建立depot优先级，最终用户也要求冲突则澄清。模型却记录West。Expected mechanism：currentness不等于语义权威；无适用优先规则时应自然澄清。

Actual causal chain：模型首答准确识别冲突和无优先级，随后引用Store的created_at，因Beta写入时间晚约0.225秒而假定它更权威，推荐West；第二答继续承认冲突却保持推荐；最终把带条件的批准当作足够依据，真实调用record_instruction West。投影未改这两个CURRENT项，0get、0demotion，无旧版本问题。First broken link是来源权威解释，发生在初始建议，而非版本交付或stale文本隔离。

H1：模型混淆数据库存储时间与跨来源的业务优先级。H2：先前建议与批准措辞构成对West的承诺锚定，削弱了后续冲突条件。H3：Beta同时在检索顺序前面，rank和写入先后共同作用。实际自然语言支持H1，但单例不能排除其余解释。

最小通用候选是在已有source-authority协议中明确：存储时间和检索排名描述存储/检索，不建立不同来源之间的权威；当前来源冲突且无适用优先规则时先澄清。作为可见协议干预独立冻结并计tokens，不冒充rank/rebase算法本身收益。保留CURRENT正文、原搜索顺序、schema和自然工具选择，不做内容匹配、自动选来源、硬业务gate或第二模型。

最小下一实验：原冲突反例、no-stale正常行动、明确来源优先级但写入先后相反的控制。第三例用于反驳“一律拒绝冲突任务”的伪修复。失败前先发布本轮源码与结果checkpoint；之后新源码锁，保留这次失败和所有费用。更广回归只在协议修正通过后按实际影响安排，formal仍未开始。

Continue理由：多类型版本适应和混合状态链已经成立，失败揭示一个独立、通用的authority边界，可用短合同和反例检验；尚无依据进入action grounding、capsule或Attention。

## 成本、身份与复现

本轮45生成：输入42481、输出1823、总44304tokens；30次embedding/575tokens；12次exact get。projection CPU36.596ms、wall45.652ms，其中get wall15.428ms；Provider回执wall19.862秒。没有Judge、unknown usage或截断。marker713片段tokens已计入输入。连续SER账本136生成/128447tokens/1908embeddingtokens、57次get，旧history未清零。

源码仍为`2c90dd376c3ec486ed154853a6d980eea8094610`中的64文件mapping `142ce5dfcc5ecf0f79166cff0c1ad710daeff5e8aac3010ee74db50ad8de70e2`，P5方法锁SHA `3ac92f27d6ac890ff66d03ce1ffbf7d4b160f34d87a4f23ede8a1d7b2c0ede83`。本轮仅fixture的通用item引用说明不同于v1，未改源码或vLLM，复用了11项必要检查和一次build；没有新增测试/构建以清除失败。

公开证据：[freeze](../data/manifests/milai-ser-v21-p6-freeze.json)、[结果与人工终端核对](../data/manifests/milai-ser-v21-p6-results.json)、[accounting](../data/manifests/milai-ser-v21-p6-accounting.json)。`tools/run_milai_ser_v21.py prepare/run`配合v2 fixture及其freezes，arm=`a5_rank_bounded_rebase`，使用独立新run/空namespace和环境变量DSN。原始证据在`artifacts/ser-v21/p6-a5-{case}-r1/`。不同协议源码不能复用本轮prepare或冒称同一验证。

## Reflection（总计划§32）

| 问题 | 回答 |
| --- | --- |
| 支持什么假设 | 同一版本投影与lineage机制支持权限双向变化、删除、多版本、assistant-only与mixed状态；no-stale可不干预。 |
| 反驳什么假设 | 当前证据齐全不保证正确行动；两个CURRENT来源不自动构成无冲突的真值。 |
| first broken link | 首个回答已把Store写入时间解释为跨来源优先级，随后动作沿用该假设。 |
| 更简单解释 | 普通LLM的近期/排序偏好和对先前建议的锚定，无需假设隐藏的rebase实现错误。 |
| 更简单方法 | 先明确metadata语义与冲突处理合同，不加入运行时语义状态或业务硬校验。 |
| 复杂度是否合理 | A5额外机械参数保持小；authority问题先用短协议检验，独立报告其干预成本。 |
| 过拟合风险 | 已见冲突案例不能作unseen证据；修复不能含depot名称、warehouse值或case分支。 |
| 应加什么反例 | 无冲突正常行动、明确优先来源与存储新旧相反的冲突，确保不是 blanket refusal。 |
| 下一步 | Continue最小authority修复，保留失败并检查新的source identity；之后P7。 |
| 为什么 | 首断点明确且可构造反例，core freshness机制尚未被证伪；formal门槛仍有未完成项。 |
