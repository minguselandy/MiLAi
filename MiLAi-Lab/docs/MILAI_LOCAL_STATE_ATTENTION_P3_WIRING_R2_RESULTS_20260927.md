# LSA WP2 G/L/LRU 小接线比较：R2

状态：`COMPLETE_WITH_SEMANTIC_FAILURES`。源码
`2b65c175c9ffe40f2e09f0327ee4f5faec87a84a`，六完整轨迹、36公开消息均完成。
G为9/12，L为8/12，LRU为6/12；完整轨迹三臂各0/2。LRU实际运行了分离的更新/维护/
读取控制，但前置新建判断漏掉初始安排。**工程接通不等于有效局部维护，P3尚未完成。**

## 冻结与验收

[预注册协议](../data/manifests/local-state-attention-p3-wiring-r2-protocol.json)保留原两脚本及
原rubric字节，每臂各一次，顺序interleaved LRU→G→L、partial G→L→LRU。所有输入均是
暴露development。新LRU最先运行以验证decoder，未使用额外探针或按结果调整顺序。
[精简结果](../data/manifests/local-state-attention-p3-wiring-r2-results.json)保留逐消息判断、
角色/子阶段费用、真实U/A、候选正文、Store统计及原始证据哈希。

L/LRU显式启用通用独立事项粒度句；G的单note合同不变。LRU从短目录选择U和may_create，
只给维护器U正文，提交后再从更新目录独立选A，来源只展开A的显式refs。三臂共同有
16000字符正文总上限、16384字节整事件来源预算，2048控制/4096Host输出、每消息13控制/
12Host调用。selector计入13次及总账，HTTP并发1，原服务参数未改。

每臂隔离namespace、Store、checkpoint和业务世界，每phase独立进程。Root核对全部36条
输入实际到达HTTP、53个临时view逐一绑定其后Host请求、持久来源原文字节、实际业务
journal与最终回答。控制/Host/embedding receipts与账本一致，无未知用量。没有transport、
容量或控制退化，末pending为0；这些机械状态不能证明模型的no-op判断正确。

## 结果与实际行为

| 轨迹 | G | L | LRU |
|---|---:|---:|---:|
| interleaved | 5/6 | 4/6 | 3/6 |
| partial | 4/6 | 4/6 | 3/6 |
| 全部消息 | 9/12 | 8/12 | 6/12 |
| 完整轨迹 | 0/2 | 0/2 | 0/2 |

G和L在interleaved的实际预留都把`east archive E-2`、`north rack N-6`当对象键，故组合
动作失败。L后台修订后的回答只有“handling summary remains unchanged”，未给出请求的
数量、目的地和包装摘要，按信息遗漏失败；存储中的字段本身正确。G能完整回答这一步。

L确实自行建出handout、field kits、briefing三张卡：第一次后台修订只改变field-kit卡，
handout和briefing仍revision1。随后普通memory工具观察引起无必要的handout措辞更新，
所以不能把整轮所有未受影响卡都宣称从未重写。partial中Mira物流与access仍合为一张，
说明通用粒度句并未保证所有事项都分开，也不要求唯一标准State划分。

partial三臂均实际get found并使用原reservation ID补标签，且没有重复预留；但三臂初始
Mira对象键均错误。G为`Summit Archive Crate`且目的地/包装改变大小写，L/LRU为单数
`Summit archive crate`。G/L的Noel对象键也错误，分别为单数与`summit-archive-crate`。G/L保留D-2/10:15，LRU没有保留access。

LRU interleaved在重启时只回答packing“unchanged”，未保留rigid cases；组合动作对handout
使用quantity1、destination/packing“unchanged”，对field kits仍用packing“unchanged”。
最后虚构briefing为Room101/10:00AM/main lobby。LRU partial的Noel动作使用quantity1、
`Archive Storage Facility`、`Standard Crate`，而非原计划；最终承认无access信息。
每个interleaved臂实际2次reserve，每个partial臂实际2次reserve和1次complete_label。

## 首断点、解释与最小修复

**Observed：**LRU最初workshop brief、Noel plan、Mira plan均得到`U=[]/may_create=false`；
维护器没有被调用。workshop的foreground询问也因同样判断跳过。原始事件仍在持久档案，
但这些pending被当作no-op消费，后续维护只有新事件与所选卡正文，缺少最初事实。
**Expected：**需要保存的新事项应有与G/L相同的共享维护机会；更新候选选择不应额外
拦截尚无State的新事项形成。

真实因果链：完整初始事件→selector实际HTTP返回false→未调用maintenance→无State且
pending清除→新会话读取没有原计划→后来的相对修订/请求产生缺项卡→实际错误动作。
首断点不是decoder、Store丢写或read selector漏选已有正确卡，而是新建机会在前选择处丢失。

竞争解释：

1. 额外布尔门槛把新事项形成交给了较短的selector，削弱共享维护器的接收机会。移除这一
   新建否决并保留已有State的U限制，应让最初事件实际进入维护。
2. 共享维护器收到这些事件后仍可能选择错误no-op、错误分组或遗漏事实。若机会恢复后
   仍丢失，下一断点在维护内容，不能把修复调用流程称为语义修复成功。

选定一个结构修复：U只控制已有State的更新正文；每个pending批由共享维护器决定
创建或no-op，不由may_create否决。空bank没有可选已有ID，可直接维护→A；有bank为
U→维护→A。保留程序逐条拒绝越U更新、控制失败隔离、真实观察、相同预算与计费。
不强制创建State、不重播旧事件、不自动按业务词切卡、不改R3来源措辞、Host或业务schema。

下一实验只运行修复后的两条原LRU完整轨迹，核对最初事件是否进入维护、真实内容及
后续行为；G/L保持本批历史参照，不为这项局部修复重新执行。不能将新LRU与旧G/L的
一次对比包装成最终同版本重复效果。新增四情景仍未执行，36轨迹正式P3批次仍不触发。

## 完整成本

| 臂，两轨迹 | controller calls/tokens | Host calls/tokens | generation合计 | embedding calls/tokens |
|---|---:|---:|---:|---:|
| G | 18 / 23,256 | 18 / 26,728 | 49,984 | 1 / 45 |
| L | 19 / 22,587 | 19 / 24,369 | 46,956 | 2 / 25 |
| LRU | 40 / 23,624 | 16 / 21,615 | 45,239 | 0 / 0 |
| 总计 | 77 / 69,467 | 53 / 72,712 | 142,179 | 3 / 70 |

LRU控制子阶段为U选择16次/5860tokens、维护12次/12901tokens、A选择12次/4863tokens。
G/L的by_control_stage为空表示没有LRU分阶段，不表示其维护免费；原by_role总账完整。
LRU更多控制calls却较少tokens，伴随漏存及更差任务质量，不能称为同质量效率收益。
模型等待合计controller85.0320s、Host30.4718s、embedding0.1434s。

连续账本从1191 / 1,440,580 / 11,092增至 **1321 generation calls / 1,582,759 generation
tokens / 11,162 embedding tokens**，本批新增130calls/142179tokens/70embeddingtokens。
历史链完全保留；LSA启动以来为458calls/540030tokens/1545embeddingtokens。

| 轨迹/臂（执行顺序） | 实际BaseStore get/search/put | 末State逻辑字节 | 末来源逻辑字节 |
|---|---:|---:|---:|
| interleaved LRU | 91/64/30 | 1748 | 3745 |
| interleaved G | 103/81/31 | 1780 | 4800 |
| interleaved L | 128/101/41 | 1733 | 4967 |
| partial G | 115/101/41 | 2309 | 5321 |
| partial L | 91/91/36 | 2149 | 4978 |
| partial LRU | 97/82/35 | 1537 | 4992 |

Root另有12次冻结前空namespace读取、12次phase后快照读取，无embedding或业务写入。
Store调用含目录全量扫描及来源解析，不能解释为SQL往返。完整checkpoint/业务数据库/
instrumentation物理字节与State/source/meta逻辑字节分别保留在精简结果。最大控制输出
664tokens，未触及2048；两LRU轨迹最大交付正文500/358字符，短是因为信息缺失，非容量优势。

## 决策与复现

**Continue最小结构修复，保留所有负结果；不扩大benchmark。**已证明L能够实现一次局部
事实更新和未受影响卡保持，但没有证明稳定泛化或LRU独立收益。G在R1 partial曾完整通过，
本次失败也保留，不能选最好重复。R1/R2相同温度不保证相同轨迹，配置和控制合同也有差异。

复现使用上述源码提交与[协议](../data/manifests/local-state-attention-p3-wiring-r2-protocol.json)，
命令同[R1复现入口](MILAI_LOCAL_STATE_ATTENTION_P3_WIRING_R1_RESULTS_20260927.md)，arm替换
为本批G/L/LRU，创建新namespace/world，按冻结顺序、每phase新进程，私密DSN只注入环境。
原始trace/冻结/快照位于ignored `artifacts/local-state-attention/p3-wiring-r2/`，不得重放原
业务副作用。源码44项相关检查、零模型prepare和必要build已在冻结前完成；本结果只做
账单、输入/证据哈希、JSON与链接核对，没有新增Judge或为发布重复模型/测试。
