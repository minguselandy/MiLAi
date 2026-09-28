# v2 N3 / X4：固定前态更新选择结果

状态：**八条冻结维护诊断完成；本切片 Pivot 独立 U，继续 N5。**
四臂都完成必要正文变化并完整保留无关记录；加入实际来源绑定要求后，all 与实际 U=A 各 2/2，独立 U 与 oracle 各 1/2。
独立 U 的候选集合更小，但调用费用超过 all，未解决简单对照留下的缺口。

[协议](MILAI_NEXT_DEVELOPMENT_V2_N3_FIXED_UPDATE_20260928.md) ·
[检查回执](../data/manifests/next-development-v2-n3-checks-20260928.json) ·
[逐项结果与制品哈希](../data/manifests/next-development-v2-n3-results-20260928.json) ·
[N2 结果](MILAI_NEXT_DEVELOPMENT_V2_N2_RESULTS_20260928.md)

## 身份与范围

方法提交 `dfbc59d39f445dd6d2c3642069e11a8a4da4ed7d`，发布于 [PR64](https://github.com/minguselandy/MiLAi/pull/64)，
base 为 PR63 的 N2 结果 `8eca99e`。正式 prepare identity 为
`4f896268f727b380e2008e8d0e9f6d9c1823f33992b8b19f9632645c6a209962`，
execution-freeze SHA256 为 `4e7bf2866b70e5325c503940c0621c99269cb98192bb0838331c0dad32736b0d`。
Root 在真实调用前将全部154项源码/入口身份与已提交 Git 字节核对。
首次本地 archive 核对因 cwd/pathspec 不匹配退出，改正 cwd 后通过；此时尚无模型调用，保留该准备记录。

输入、配置、rubric 哈希与协议完全相同。两个前缀来自同一个已暴露的三条 State 前态；
background 是原实际用户更新，new_topic 是已声明的构造新事项。八条条件不是八个独立样本。
原始 seed 中 evidence_refs 为空且没有历史依赖元数据，原样保留。

只执行一次候选选择（需要时）和一次整体维护提案，各 job 独立 namespace/Store/checkpoint 路径，Root HTTP 并发1。
模型仍为 Qwen3.6-35B-A3B-FP8，控制 max_tokens=2048、temperature=0、thinking=false；无部署或服务配置调整。
普通 memory 为空且不开放写入，质量为 NA；没有 Host 回答、业务动作、N4反馈或模型 Judge。
本结果不能替代完整 CRUD、两库一致性、业务消费或 N5 生命周期验收。

## 结果与实际选择

| 条件 | 必要正文＋无关保持 | 实际来源绑定 | 严格联合 | 生成调用 | 选择 tokens | 维护 tokens | 总 tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| all | 2/2 | 2/2 | 2/2 | 2 | 0 | 1,846 | 1,846 |
| 独立 U | 2/2 | 1/2 | 1/2 | 4 | 736 | 1,374 | 2,110 |
| 实际 U=A | 2/2 | 2/2 | 2/2 | 4 | 887 | 1,579 | 2,466 |
| oracle U，仅诊断 | 2/2 | 1/2 | 1/2 | 2 | 0 | 1,386 | 1,386 |

“来源绑定”依据冻结 rubric 的 linked/cited source 要求，核对实际 `evidence_refs`。
程序保守记录的 `dependency_source_ids` 以及正文里的 Source 字符串单独报告，不当成已建立的证据链接。
这个严格分项不抹去正文正确或创建成功，也不把缺链接改称正文错误。

| 前缀 | all | 独立 U 的真实输出 | A 的真实输出，直接用作 U | oracle |
| --- | --- | --- | --- | --- |
| background_change | handout、field、welcome | field | handout、field | field |
| new_topic | handout、field、welcome | 空 | handout | 空 |

background 四臂都只更新原 field ID，版本1→2，正文为8 kits / north rack N-6 / rigid cases，引用真实新用户事件。
handout 和 welcome 的全部存储字段保持不变，没有重复事项或虚构业务结果。

new_topic 四臂均实际创建一个 A-6 / 08:00–16:00 事项，三个旧记录全部字段保持不变。
独立 U 的实际空集和 oracle 空集都没有阻断 CREATE；新 ID 均由 Bank 生成。
但独立 U 提案省略 evidence，oracle 把来源 ID 写进 content，也省略 evidence，因此两者实际 evidence_refs 均为空。
两者仍有保守 dependency_source_ids，且 `dependency_unknown=true`：这是旧前态依赖覆盖未知下的程序标记，不能认证模型引用或语义依据。

所有八个 job 为 APPLIED，pending 均清空，没有部分拒绝、超时、容量或格式失败。
这说明执行层接受了提案，不说明每个来源要求已完成；两条缺链接记录正是不能只看回执和 ack 的例子。

## 实际链路核对

Root 核对每条真实 `vllm_response.request`：新观察与冻结输入逐字段相同，维护正文只含实际选中集合；
各臂提示和维护规则相同，schema 中允许的旧 ID 随真实集合变化，CREATE 在全部条件可用。
U 只额外接收观察与短目录；观察自身提到前台任务，原文没有被人为删改。
U=A 使用 N2 的真实 A helper，没有人工注入预期读集合。运行时不读取 rubric。

模型实际响应逐字段等于记录的 proposal；回执、数据库回读、版本、来源、ack/pending 对应实际提交。
12个 provider generation ID 唯一，按 selector/maintenance 互斥归类，原账本增量完全一致。
U 与 oracle 的 background 维护请求对象相同，new_topic 的维护请求对象也相同；后一对响应正文不同，但两者都漏了结构化 evidence。
因此不能将那12个输出 token 差解释成选择算法压缩，也不能从单次响应确定后端差异成因。

本切片没有后续 Host 消费，证据链止于实际持久化与 pending；后续行动由 N5 另测。

## 首断点与反思

Observed：空 U 正常创建正确新正文，却没有显式证据链接；oracle 也出现同类缺口。
Expected：创建新事项并绑定真实新用户观察，同时保持旧事项。
实际因果链：合法新事件与可用来源 ID → 模型生成无 evidence 的提案 → 既有可选 evidence 合同接受 →
Bank 保存正确正文、空 evidence_refs 与保守未知依赖 → 成功回执并清 pending。
首个缺口是维护提案没有表达结构化来源关系；不是 selector 漏选旧对象，也不是 Store 丢失已经提供的 evidence。

至少两个解释仍需区分：共享 schema 允许省略 evidence，模型未落实可用来源引用要求；
空候选时少了带 evidence_refs 字段的 State 示例，可能改变输出形式。当前两前缀不足以把后者确认为原因。
实际原文/来源 ID 已进入 HTTP，排除了本轨迹“输入缺失或只送了目录”的解释。

通用修复候选是明确来源字段的输出合同或共同字段投影，并保留 unknown 的真实含义；
但这不是确定的存储程序故障，本轮不改提示或强制补引用后重做暴露样本。
程序自动补 evidence 会混淆保守输入依赖与模型表达的证据，不能用来修分。
若以后该缺口导致真实后续任务失败，再对共同维护合同做独立版本诊断；不追加 selector 训练。

本轮没有全流程/独立任务族证据，没有显著性或等价性结论；oracle 获得人工 mask，其低费用不能列为部署方法成绩。
原始前态形成成本未测，且新事项为合成开发请求。这些混杂和失败均保留，不替换样本，不追加选择性修复。

## 费用与存储边界

新增 **12 次生成 / 7,808 tokens**，其中输入6,666、输出1,142；embedding调用/token均0。
真实生成 HTTP wall 合计9.037664741743356秒，非端到端时间或GPU计费。
连续账本从2818 / 3504405 / 20093变为 **2830 / 3512213 / 20093**（调用/生成token/embedding token），
终点 SHA256 `b41871849789b7961c088c6c2750f28f98fc94fb268f73c51004b120d543adc7`。
当前 unknown usage=0；sealed历史原样保留，开发代理和CI费用不混入。

独立 U 维护阶段比 all 少472 tokens，但选择本身736 tokens，使总费用增加264（约14.3%）。
U=A 总费用比 all 增加620（约33.6%）。不能只展示维护段节省。
候选正文序列化字节在 background 为679/217/443/217，在 new_topic 为679/2/226/2；空数组的2字节不是零输入。

八条路径各有9 get、13 search、7 Bank put，未因 U 缩小减少全量目录/提交核对扫描。
Bank合计72 get、104 search、56 put；另有24次直接 seed State put，普通memory put为0。
seed事件/ack及观察已包含在 Bank 指标，不能再加一次。
逻辑请求/结果字节、局部CPU/wall明细见清单；物理I/O、完整进程wall、原始形成成本未测，保持unknown。
不由少量候选或一次诊断推导20%生命周期节省。

## 决策与复现

**Pivot 独立 U 生成阶段。** all 已满足本切片的变化、保持和来源要求且最省；真实 U=A 也没有额外质量收益。
这不证明所有规模或 retrieval-based U 无效；后者未运行。不为制造收益添加任意干扰记录。
N2同样没有独立A收益，因此下一最小连续比较关闭独立A/U与N4。

N5 将比较共同 Host 双库CRUD/完整合法历史条件下的 H_shared 与 all_shared，唯一读取差异为是否预交付 State 正文。
其问题是在线形成后的正文预交付能否改善实际业务或抵消费用；不是重新声称独立selector有效，也不是原生B1复现。
原生 MERIT 任务/world/checker 与构造补充单列，N5实现及输入另冻，当前结果不能预先认定候选获胜。
N6仍未触发，Product仍NO-GO。

复现使用本方法提交、协议中的三JSON及锁定foundation环境。先以新run ID/namespace执行prepare并绑定rubric，
注入已忽略的私密DSN后按1–8顺序各run-job一次，`--stage next-development-v2-n3-fixed-update-r1`；
仍追加原连续账本，不能在本次已尝试job目录上重跑。原私密HTTP/数据库不发布，精简提案、回执、评分和哈希已发布。
