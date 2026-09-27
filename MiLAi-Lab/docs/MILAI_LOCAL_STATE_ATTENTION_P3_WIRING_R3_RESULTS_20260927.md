# LRU 新建机会修复：真实结果

状态：`COMPLETE_WITH_SEMANTIC_FAILURES`。源码
`eda7add22d3a78f6074098c800fad36707ed7dd2`；按
[冻结协议](../data/manifests/local-state-attention-p3-wiring-r3-protocol.json)
只运行两条原 LRU development 轨迹，4 个独立进程 phase、12 消息全部完成。
[精简证据与哈希](../data/manifests/local-state-attention-p3-wiring-r3-results.json)
保留实际请求、阶段快照、计费角色、U/A、Store 操作及首断点。
R2 G/L 仅为历史参照，不拼成新的匹配比较。

| 轨迹 | 严格消息 | 完整轨迹 | 主要结果 |
| --- | --- | --- | --- |
| 交错/后台更新 | 4/6 | 0/1 | 初始三事项都保存；修订丢失具体包装，恢复和实际行动失败；briefing 保留 |
| 部分失败/双 owner | 4/6 | 0/1 | 实际 found 并沿原 ID 补 label；两 owner 初始业务 key 仍错误；access 保留 |
| 合计 | 8/12 | 0/2 | 不用接口成功代替语义验收 |

## 断点、解释与决策

Observed：空 bank 跳过无意义 U selector，三处初始计划全部进入共享维护器；交错形成
3 卡，Mira 仍把物流/access 合成 1 卡。此前的新建否决断点已解除。
Expected：保留未修订字段，后续恢复和实际业务应消费完整当前协议。

交错后台更新的 U 正确选中 field kits。实际维护 HTTP 的旧 State 明确含 `rigid cases`，
新事件只改数量和目的地；输出却把包装替换为 `Packing stays the same`，引用仅保留新事件。
持久化接受该内容，新 session 的 A 交付此卡及新引用，具体旧包装没有进入实际 Host 请求；
Host 先回答无法确定包装，随后真实 reserve 使用 `packing="same"`。手册包本次全部字段正确。
首断点在正确候选已到达后的维护内容丢失，后续来源选择也未补回信息。

H1：更新候选漏选造成丢失。本次精确 HTTP 反证了这个局部解释。
H2：维护器将增量措辞当作完整替换，且显式引用不能覆盖被省略的旧事实。本次链路支持 H2，
但不证明这种失败在其他模板必然发生。不能通过机械补取全部历史掩盖当前臂的真实行为。

部分失败按实际回执保留 reservation；恢复 get 返回 found，complete_label 使用原 ID，
没有重新 reservation。初始 Mira key 为 `summit-archive-crate`，Noel 为
`Summit archive crate`，均不等于用户的完整对象，原失败继续计分。
Noel 后续 U 两次为空，维护器分别新建请求/回执卡；结束时 Noel 有 3 卡。
新建机会修复避免静默丢事件，但不保证合并、去重或正确粒度。

Continue：保留当前版本，进入六模板 G/L/LRU、各两次完整运行的预注册小样本比较，
区分表示、保持及选择失败的范围，并记录总成本。这里继续的是已接线的方法比较，
不宣称 P1 语义全过或组件已有独立收益。暂不新增 prompt、selector 训练或参数扫描。
若多模板重复仍由 G/L 解释掉收益，再按规划简化；条件式 LR/R/U=A 用于具体差异归因。

## 成本、验证与局限

本批新增 **61 次生成 / 51,693 generation tokens / 0 embedding tokens**。
控制器 45 次/29,226 tokens，Host 16 次/22,467 tokens；实际 HTTP 用时分别
34.785s/9.307s（相加不是完整进程耗时）。控制细分：U 13 次/5,597 tokens，
维护 16 次/16,715 tokens，A 16 次/6,914 tokens。全部 unknown=0。
连续账本现在为 **1,382 次生成 / 1,634,452 generation tokens / 11,162 embedding tokens**；
历史成本链字节未变。LSA 从原起点累计 519 次/591,723 generation tokens/1,545 embedding tokens。

实际 BaseStore get/search/put：交错 99/64/33，partial 105/82/37，失败均 0；
目录仍扫描完整记录，只能声称维护模型的候选正文减少，不能声称物理读取减少。
结束 pending=0、degraded=0、容量错误=0；这些不等于语义 no-op 正确。
16 个 State 视图均按顺序绑定真实 Host HTTP；31 次展开事件交付的正文与原记录一致，
没有 missing/deleted/invalid/预算省略。business_calls 在同 session 累计，动作按去重 journal
和真实 world attempts 计数，不能逐消息相加制造重复副作用。

源码先前 45 项相关检查、静态及必要构建结果沿用，未为报告重跑。
本轮只做实际输入/HTTP/来源字节、持久化、世界动作、成本与哈希核对。
两模板已暴露、每臂一次且只有 LRU，8/12 不是稳定收益；完整 Goal 仍 ACTIVE，Product NO-GO。
