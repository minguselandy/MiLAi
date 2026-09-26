# P7 R2：局部失败隔离成立，记忆缺口仍在

两臂用同一原始arc、空namespace和原容量重跑。B1 native 4/5、dependent 1/2；A5 native 3/5、dependent 0/2。A5在episode 2容量失败后确实进入episode 3并退款成功，episode 4再次容量失败也被记录。覆盖修复成立，语义回归未收敛；TERMINAL不代表全部Host消息完成。

## 冻结与验证

前身为已发布的`69c1a2ba9fecf3c90a1f8427f0dafe300985fe44`。本轮只增加默认false的`continue_on_local_capacity`，R2配置两臂均启用。原scorer、业务副作用、失败消息额度、authority、SER算法和vLLM设置不变。保存失败消息与skipped索引后继续下一episode；服务/Store/instrumentation错误仍中止。

- 67文件mapping：`2abbd10cb971d9df81bf2a4dd78585478eb56bb1517ffec9f94d2b688c6c25d5`。
- [R2源码锁](../data/locks/milai-ser-v22-p7r2.lock.json) SHA=`7d9c8b0b6ed307d3c565967764846924631e3b239ba76411018bb628c66e82e1`。
- [方案](MILAI_SER_V22_P7_R2_PLAN.md)、[调用前冻结](../data/manifests/milai-ser-v22-p7r2-freeze.json)、[汇总](../data/manifests/milai-ser-v22-p7r2-results.json)保存输入SHA、参数、两臂身份和连续账本。

两个必要离线反例通过：容量耗尽前已发生的业务成功按原checker保留，下一episode继续；服务故障仍中止。ruff、mypy两文件、CLI/config与diff检查通过，一次必要build包括新config/lock。没有重复十二例或整组测试。旧R1从前身commit复现，原锁与失败不覆盖。

## 实际行为

| 指标 | B1 | A5 |
| --- | ---: | ---: |
| native | 4/5 | 3/5 |
| dependent | 1/2 | 0/2 |
| Host完整episode | 5/5 | 3/5 |
| 已尝试公开消息 | 7/7 | 6/7 |
| 已完成公开消息 | 7/7 | 4/7 |
| 容量失败消息 | 0 | 2 |
| 跳过消息 | 0 | 1 |

B1仍没有保存episode 0/1的2492→1774约定。episode 2先空搜，随后凭空创建5000金额记忆并实际退款5000，原checker判失败。它保存该episode第二条消息明确给出的6595，episode 4搜到后正确退款；成功后记忆仍保留“Do NOT process it yet”，动作后维护缺口未解决。episode 3全额16100正确，但回答的5–10工作日到账估计没有工具依据。B1没有触发隔离，不能将本次全程完成归因于隔离开关。

A5同样未保存早期约定，虽然客户消息声称“updated our records”。episode 2空搜索耗尽额度，其第二条6595消息未尝试，影响后续依赖任务。episode 3全额16100成功，证明真实错误之后继续；episode 4误把query传给manage_memory，实际创建content=null，随后删除，再次空搜耗尽额度。两次操作收据及null内容已核对，未把它称为有用记忆形成。两个依赖退款均未执行。

Root阅读了完整答案、工具参数、业务回执和Store内容。原native memory字段来自checkpoint；A5实际Provider中也没有任何memory item，33次projection/4条ordinary lineage、0demotion/0版本get。null插入后删除没有被search返回，不能算自然stale召回或rebase成功。B1的6595检索/实际退款对应同一当前值，但不证明逐词因果采用。

## Failure Review

Observed failure是早期约定未形成、后续猜测或空搜循环；Expected mechanism是普通记忆工具保留未来仍需使用的信息。Actual chain为确认消息→0记忆→新episode信息不可用→B1猜5000/A5重复空搜。First broken link仍是Formation，不是SER隐藏了内容。

H1：普通Host不稳定识别未来信息价值；H2：写入后被scope、检索或投影丢失。早期0写入和空Store支持H1、反对H2。H3：无证据authority扰动工具决策；所有A5请求都额外带63tokens，但单run与温度0仍有轨迹波动，不能由分差证明因果。R1/R2的B1本就出现不同路径，是重要混杂因素。

最小通用下一修复：仅当实际projection.items或derived_rebases非空时添加authority。不依赖问题内容、case或预期答案；current/unknown冲突和assistant-only stale反例必须继续保留原则。离线[空authority分析](../data/manifests/milai-ser-v22-p7-empty-authority-analysis.json)表明原十二例20/20首个公开请求在只删该片段后与B1完整wire一致；这是结构证据，不是重跑或质量收益。

Decision为Continue。先消除不必要的协议干预，再冻结P7对照；Formation与Reconciliation按总计划独立研究，不能混入SER收益或靠扩大额度掩盖。null memory与空搜索循环也应独立解释，不添加金额/退款规则。

## 费用和存储

| arm | 生成 | input/output tokens | 总tokens | embedding请求/tokens |
| --- | ---: | ---: | ---: | ---: |
| B1 | 21 | 20186/1050 | 21236 | 5/100 |
| A5 | 33 | 35698/1169 | 36867 | 15/113 |
| 合计 | 54 | 55884/2219 | 58103 | 20/213 |

连续SER现为360生成/332460tokens/3902embeddingtokens/75版本解析get，unknown/truncation/Judge均0。容量错误另计，不等于输出截断。A5额外authority片段63×33=2079tokens已含在实测费用中，不再次加总。历史失败费用全保留。

projection CPU16694716ns/wall11926726ns，Provider收据wall23.624234秒；两进程wall分别16.936087/23.228672秒。trace1495194 bytes、instrumentation389120 bytes、checkpoint786432 bytes；journal/共享PostgreSQL另计，persistent semantic State为0不等于总存储0。observer额外Store读8次与版本解析get0分开。rebase/refresh精确率与召回率分母0，均undefined。

## Reflection

1. 支持：局部容量错误可隔离，原世界checker和已发生副作用可保留。
2. 反驳：完成整个评估循环等于Host全部完成或语义正确。
3. 第一断点：早期信息未保存；ep4还受前一消息skipped影响。
4. 简单解释：无memory输入时SER无法恢复约定，B1的轨迹波动足以造成分差。
5. 简单方法：按机械证据条件添加authority，不加入新模型或语义gate。
6. 复杂度：局部catch与消息索引是覆盖需要；无证据authority仍可削减。
7. 过拟合：全部为已暴露开发数据，修复须完全不读case/答案。
8. 反例：current冲突必须有authority，只有失效assistant而无搜索项也不能漏掉authority。
9. 决定：Continue P7，P8尚未冻结；P9–P12保持ACTIVE。
10. 理由：覆盖链已修复，有独立可检验的成本修复；生命周期问题另行解决，不能归档后停止。

复现：用R2锁/config及freeze中的CLI参数，新输出与namespace；并发1，原账本不清零。Product Schema/API/权限/Canonical不变。Luna发布此检查点后再修改下一候选。
