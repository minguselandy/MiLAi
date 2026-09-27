# LSA WP2 G/L 小接线比较：R1

状态：`COMPLETE_WITH_SEMANTIC_FAILURES_AND_UNREALIZED_LOCAL_PARTITION`。
源码为 `053a5ed08b6e01f826997e7b1158d7a9de033fc5`；四条完整轨迹、24 条公开消息均执行完成。
G 为 11/12、完整 1/2；L 为 9/12、完整 0/2。**L 本批也只生成每 owner 一张卡，预期的
局部划分没有形成，因此分数差不能归因为局部表示。**完整 LSA Goal、P3 与 LRU 仍未完成。

## 协议与实际链路

[预注册协议](../data/manifests/local-state-attention-p3-wiring-r1-protocol.json)固定原两条已暴露
development 脚本与原 rubric，顺序为 interleaved G→L、partial L→G，各一次。未替换样本、
拼接成功后缀或改分母。[精简结果](../data/manifests/local-state-attention-p3-wiring-r1-results.json)
含每消息判断、角色账单、Store 操作、资源字节与原始证据 SHA-256。

G 是每 owner/workspace 一条笔记；L 允许多个 State。共同使用原维护机会、来源合同、
all_sources 读取、16384 UTF-8 字节整事件来源预算、16000 字符 State 正文总上限。
G 单卡上限 16000，L 单卡 4000、最多32张。标题、needs、引用和原始来源另计。
Host 4096、controller 2048、每公开消息12/13调用及原服务设置未变，HTTP并发1。
本批没有截断、容量耗尽、transport错误、控制降级或末尾pending。

发布后由实际 prepare 绑定源码、依赖、配置和输入；runtime配置仅将空 tokenizer 路径替换为
既有本地资产路径。每臂使用独立 namespace、Store、checkpoint 与业务世界；每 phase 独立进程。
Root 从真实 HTTP、phase结果、持久 Store 快照及业务 journal 评分，没有运行 LLM Judge。
全部24条原始公开输入到达实际 Host 请求；36个临时视图均与实际请求及持久来源核对。
来源正文是原事件完整内容，不从机械删除依赖补来源，也不读取 rubric/gold。

## 任务结果

| 原轨迹 | G | L | 关键事实 |
|---|---:|---:|---|
| interleaved | 5/6 | 5/6 | 两臂恢复8/N-6/rigid及R-3/14:30/step-free；组合行动均错对象键 |
| partial | 6/6 | 4/6 | 两臂均实际get found并沿原ID补标签；G初始及第二owner动作也正确 |
| 合计 | 11/12 | 9/12 | 原完整轨迹分别1/2、0/2 |

G interleaved 实际将 `east archive E-2`、`west dock W-4`作为 item_key；L 实际使用
`handout_packs`、`field_kits`。数量、目的地及包装正确不抵消对象键错误。G最后用正确对象
名称描述了错误键的成功回执，因此不能仅按流畅回答判通过。每臂实际预留恰好两次，无
额外补标签或提前业务动作。

L partial 的 Mira 初始键是 `Summit archive crate`，与原用户完整复数名不符。重启后get
使用实际持久单数键并found，随后以同一ID完成label：恢复链通过，但初始错误仍失败。
Noel实际键是 `Summit archive crate S-8 South Bay`，目的地是 `South Bay`，均不等于原字段。
G partial 使用两owner各自的完整对象名和正确字段，Mira重启后读取真实对象、原ID补标签，
没有重新预留或宣称物理发运。两臂保留D-2/10:15，每臂总计2次reserve、1次complete_label。

## 首个断点与竞争解释

**Observed：**L第一条维护就将三项workshop事务合成 `Workshop logistics tracking`；Mira
把物流与单独access合一张。之后直到运行结束，各owner仍一张卡。**Expected：**对能够
独立更新、恢复的事项形成局部对象，才可能观察未受影响卡的保持与稀疏更新。

实际链是原始输入完整到达controller→多编辑schema允许创建多个对象→模型仅提议一张
综合卡→真实Store保存→all_sources完整交付该卡。首断点在模型生成的事项粒度，不是
runner将多张卡丢弃。G的单卡限制及L的多卡容量也已在实际manifest核对。

两个竞争解释：

1. 原局部提示没有明确“独立更新/恢复”的粒度，模型按共同主题词把事项合并。若加入
   最小通用粒度约束后，在不提供正确分组的情景中产生可独立保持的State，支持此解释。
2. 当前样本很小、主题相关且维护输出偏好单卡，单靠表示合同仍不能稳定形成有用分区。
   若不同事项关系下仍合并，或分卡增加却没有保持/成本收益，就应简化或重设维护方式。

另一个独立断点是Host参数使用：interleaved两臂的当前用户请求有完整对象名，G在行动前
还展开了原计划和修订来源，仍错用地点键；L有正确事项事实，仍生成缩写键。竞争解释是
摘要实体表达改变了使用方式，或Host本身不能稳定把精确实体映射到业务参数。已有证据
不支持把所有动作错误都归为信息未保存，也不支持靠renderer硬改业务参数。

来源字段也不是完整语义支持证明：G partial最终正文正确描述label完成，但显式refs仍
只有原请求和旧部分失败回执；新get/complete来源ID写进正文，没有同步成为显式refs。
原始真实回执均保留，这一限制不应被“引用合法”掩盖。

## 成本与资源

| 臂 | controller calls/tokens | Host calls/tokens | generation合计 | embedding calls/tokens |
|---|---:|---:|---:|---:|
| G，两轨迹 | 20 / 25,381 | 20 / 30,305 | 55,686 | 3 / 173 |
| L，两轨迹 | 16 / 17,204 | 16 / 20,541 | 37,745 | 0 / 0 |
| 本批 | 36 / 42,585 | 36 / 50,846 | 93,431 | 3 / 173 |

G总generation比L多17,941tokens，约47.5%。两臂实际普通memory操作、引用、循环次数与
正文长度不同，不能把差额都当成单笔记重写开销，也不能称L的低成本证明局部压缩。
模型等待合计controller54.7378s、Host20.2778s、embedding0.3003s；不是独立样本置信区间。

连续账本从1119 / 1,347,149 / 10,919增至 **1191 generation calls / 1,440,580 generation
tokens / 11,092 embedding tokens**。本批未知用量0，保留全部历史失败成本；既有SER
exact-version reads107与下列LSA Store get不是同一指标。LSA启动以来新增328calls、
397,851generationtokens、1,475embeddingtokens。

| 轨迹/臂 | 实际BaseStore get/search/put | 末State逻辑字节 | 末来源逻辑字节 | 来源激活视图/全部视图 |
|---|---:|---:|---:|---:|
| interleaved G | 156/101/37 | 1367 | 5308 | 8/10 |
| interleaved L | 77/71/27 | 1063 | 3740 | 2/7 |
| partial L | 97/91/36 | 1957 | 4988 | 5/9 |
| partial G | 113/101/41 | 3176 | 5325 | 8/10 |

来源累计展开50次事件交付（含重复）、22227 UTF-8字节，未出现超限省略、缺失、删除或非法
引用。G/L相同访问权不等于实际模型选择了相同refs。四轨迹最大交付正文依次666、457、
566、1113字符，最大controller输出依次543、431、390、508tokens，预算均未成为首断点。
显式no-op回执分别2、0、1、0；无编辑调用另外存在，不能把“没有noop回执”解释为强制重写。

Store计数来自实际bank访问，含source resolver；不是SQL往返或物理页计量。Root冻结前
8次空namespace读取及8次phase后快照读取单列为观察访问，没有embedding或业务写入。
原始来源/State/meta逻辑字节与checkpoint、instrumentation、world SQLite物理文件分别保留；
详细值在精简结果，不把checkpoint当免费记忆。序列化请求JSON字节是构成计量，非网络包字节。

## 决策、局限与复现

**Continue WP2 implementation；不宣称P3通过。**保留G作为真实有效的强普通基线。
下一最小切片先落实通用局部粒度及LRU更新候选/读取选择，检查真实正文候选是否缩小、
U/A能否不同；不把原联合edits+focus简单改名。来源身份合同不再措辞微调，不改业务schema
或vLLM，不启动36轨迹或广泛参数扫描。新方法必须有自己的冻结与少量接线验证。

这是两条暴露模板各一次的在线比较，不是固定bank消融、稳定优劣或unseen效果。G恢复
成功不能代替局部多State目标；L卡数可配置也不能代替实际局部表示。后续共享约束、
高耦合反例、跨模板、LRU、公开任务重复、第二模型等要求继续未完成。

复现请checkout上述源码提交，使用协议固定的脚本、rubric和配置；只注入私密DSN与真实
tokenizer路径，创建新run/namespace/world，不重放原业务副作用。入口：

```bash
.venv/bin/python tools/run_local_state_attention.py prepare --config <runtime-config> --script <frozen-script> --run <new-run> --arm <arm> --repeat 1 --runtime-root <new-root> --output <new-root>/prepared.json
.venv/bin/python tools/run_local_state_attention.py run-phase --config <runtime-config> --script <frozen-script> --run <new-run> --arm <arm> --repeat 1 --runtime-root <new-root> --prepared <new-root>/prepared.json --phase 0 --stage <new-stage>
.venv/bin/python tools/run_local_state_attention.py run-phase --config <runtime-config> --script <frozen-script> --run <new-run> --arm <arm> --repeat 1 --runtime-root <new-root> --prepared <new-root>/prepared.json --phase 1 --stage <new-stage>
```

原始冻结及trace留在ignored `artifacts/local-state-attention/p3-wiring-r1/`。相同temperature=0
也不能保证同轨迹；重新运行属于新成本和新重复。源码相关32项检查和必要build在冻结前已
通过，本结果只做JSON、引用、输入/证据哈希及账单核查，未为发布重复测试或模型调用。
