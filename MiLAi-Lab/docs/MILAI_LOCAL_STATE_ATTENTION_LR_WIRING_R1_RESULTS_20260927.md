# LR 小接线 R1：独立读取可运行，效果仍未隔离

状态：`COMPLETE_SMALL_WIRING_WITH_OPEN_SEMANTIC_FAILURES`。提交
`857b80c7bc217d78c63b4f4d5dc0528b96a16f6c` 按
[协议](../data/manifests/local-state-attention-lr-wiring-r1-protocol.json)完成六条轨迹、十二个独立
phase 进程、36条公开消息；[完整精简结果](../data/manifests/local-state-attention-lr-wiring-r1-results.json)
保留每条判断、费用、实际来源和持久化证据哈希。每格一次，全部为已暴露 development。

| 臂 | interleaved | partial | 合计 | 完整轨迹 | 生成调用 | 生成 tokens |
| --- | --- | --- | --- | --- | --- | --- |
| L：全维护、全读取 | 5/6 | 4/6 | 9/12 | 0/2 | 34 | 44,872 |
| LR：全维护、独立读取 | 6/6 | 4/6 | 10/12 | 1/2 | 51 | 53,386 |
| LRU：更新选择、独立读取 | 4/6 | 4/6 | 8/12 | 0/2 | 65 | 55,262 |

LR 本批比 L 多一条正确回答，同时贵19.0%；LRU比LR贵3.5%，且没有更好的任务成绩。
这不构成稳定质量—成本优势或纯 U/A 因果结论。L/LRU初始都形成一张综合卡，LR形成三张独立
事项卡，轨迹在读取选择前已经不同。LRU另保留候选限制措辞，不能用三臂名字掩盖这些差异。

LR的17次实际维护均交付全部已有State候选，未调用U；其维护prompt与L完全相等。LR/LRU
实际A的prompt相等，均在维护之后使用更新目录，新卡也实际被选择。动态ID/正文属于各自
在线轨迹；mock验证的请求合同相等不意味着真实后续请求字节相等。

| 臂 | maintenance tokens | U tokens | A tokens | Host tokens |
| --- | --- | --- | --- | --- |
| L | 18,299 | 0 | 0 | 26,573 |
| LR | 21,148 | 0 | 6,907 | 25,331 |
| LRU | 18,072 | 5,451 | 6,453 | 25,286 |

每臂均17次维护。LR/LRU各17次A，LRU另14次U。LRU送入维护的正文字符仍为当时完整bank的
93.0%，本例小bank的缩减不足以证明selector值得付费。目录构造仍扫描完整Store，不能把
模型正文缩减称物理读取节省。

## 实际失败链与竞争解释

L interleaved 的前五条及两次预约完全正确。trace28维护在用户说不要操作简报事项时，把
简报的房间/时间/入口从综合State删掉；trace33只保留已完成预约。初始来源未加入显式
evidence_refs，最后来源展开无法补回。Host最终虚构Room101/9AM/main lobby，而非
R-3/14:30/step-free。LRU trace49出现相同丢失，U已经选中了该综合卡；最后新建的是没有
答案的简报询问卡，Host承认缺信息。其两次预约还把完整对象名改成handout_packs/field_kits。

Observed：相关更新和当前行动正常，但无关事项保持失败。Expected：排除某事项的业务行动
不应丢失它的既有安排。首断点在维护重写。H1是综合分组使全卡重写更容易丢失独立事项；
H2是维护器把行动排除理解为信息丢弃，且缺初始来源引用使读取无法恢复。这批在线分叉不能
区分分组与selector的独立贡献，不再据这两个旧例增加措辞。

三条partial都在两位owner首次预约时改写精确item_key：单数或下划线形式。数量、地点、
包装和用户隔离正确，但这两条消息均按原严格标准失败。实际ok=false保留了预约，重启后
三臂均get found，再按同一真实ID完成label，没有再预约或虚构dispatch；这项恢复通过，
不追补最初的错误对象键。门禁已说明完整对象名，首断点仍是Host参数选择。竞争解释是
Host将名称规范化成工具key，或受State单数标题/自身记忆措辞影响；本批不另加对象规则。

LR partial末State将初次尝试称为“failed”，但保留实际预约及后续成功标签；局部可恢复不
代表所有状态措辞准确。LR interleaved简报卡把来源ID放在正文而非evidence_refs，答案正确
也不证明引用维护完整。没有控制降级、容量失败、异常或末pending；这些机械指标不是语义验收。

## 成本、核对与下一步

本批新增 **150次生成 / 153,520 generation tokens / 154 embedding tokens**（3次embedding）。
其中控制99次/76,330tokens，Host51次/77,190tokens；生成HTTP合计131.090s，embedding0.295s。
连续账本为 **2,574次生成 / 3,183,881 generation tokens / 18,337 embedding tokens**，
unknown=0，历史费用链不变。运行内Store共700get/465search/214put；Root另有12次namespace
预检和12次phase快照读取，无额外embedding或写入。各类存储逻辑字节在精简结果中单列。

51个实际视图与Host HTTP逐一绑定，122次来源交付与真实持久事件正文相符；没有漏读、
删除引用、无效引用或预算遗漏。源码/config/输入身份、全部用户消息、51次events-only维护、
真实业务参数/回执、phase快照和ledger均核对。Host时点候选仍未加入live。
53项源码检查、两条LR零模型prepare和一次构建沿用发布前记录，没有为报告重跑。
按协议run_order，在此提交上用原CLI prepare/run-phase、新namespace和隔离目录复现；
两个phase独立进程，私密DSN只注入环境，不提交原始轨迹或数据库。

决策为Continue强基线、暂不扩大selector调参：LR接线有效，当前证据仍允许“简单全笔记/全历史
已经足够”这一解释。最小下一实现是共同的合法历史读取入口和完整历史对照，再补滑窗摘要/
按需重建。读取已发生的公开checkpoint消息并计费，不能把私有observer档案只交给某臂。
不重跑本批挑成功、不修措辞直到所有旧Host错误消失，也不把本小切片称六项消融或全Goal完成。
P5–P7、独立模型与授权删除等剩余义务继续；Product仍NO-GO。
