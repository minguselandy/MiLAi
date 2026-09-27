# LSA P1 R5：显式来源展开恢复了本例的精确读取

源码 `51244424def98b6acde7be9ffd18e2f5d5309581`，
[冻结协议](../data/manifests/local-state-attention-p1-r5-protocol.json)，
[精简结果及证据哈希](../data/manifests/local-state-attention-p1-r5-results.json)。
两条原 partial-restart 轨迹、四个独立进程 phase、12 消息全部完成。
控制器、State 读取方式、Host 与业务工具合同相同，只切换引用来源的临时展示。

| 结果 | 来源 on：local_all_sources | 来源 off：local_all |
| --- | ---: | ---: |
| 严格消息分数 | 4/6 | 3/6 |
| 完整原轨迹 | 0/1 | 0/1 |
| 恢复 get 读到实际对象，再沿原 ID 补标签 | 是 | 否：get 为 not_found，补标签仍成功 |
| 初始 Mira 对象 key 符合原约定 | 否 | 否 |
| Noel 对象 key 符合原约定 | 否 | 否 |

on 的真实请求含原始部分失败回执，Host 的 get 使用实际已持久化的
`Summit archive crate`，返回 found，再使用同一真实 reservation ID 补标签；没有再次
reserve，也没有虚构 dispatch。off 把 reservation ID 当成 item_key，get 返回 not_found，
但仍正确使用该 ID 完成标签。二者最终标签都存在，不能用末态抹去错误读取。

两臂初次都把用户的完整复数名称 `Summit archive crates` 改成单数，Noel 则分别用了
单数和下划线变体。来源展开没有修复这些错误，两条完整轨迹仍严格失败。两个计划确认
及最后 D-2/10:15 回答均通过；额外的一分仅来自本次恢复 get 的真实成功。

## 从来源到实际请求

on 的 10 次 Host 请求中 5 次实际展开来源，另外 5 次没有显式引用，不回退到机械依赖
或整个档案。共有 12 次事件交付（含跨请求重复），来源块累计 5819 UTF-8 字节，0 missing/
deleted/invalid/over-budget。每条 id/kind/actor/tool_call_id/content 都与同 owner 的
实际事件快照逐字段一致，并独立核对其完整进入真实 Host HTTP。

恢复首请求获得 2 条显式来源、977 字节，其中原工具回执提供完整 item_key。State 摘要
只有自然语言对象称呼、条件及 reservation ID，不能替代原回执字段。未生成新的工具
回执、未修改业务参数、未读取 rubric 或派生正确答案。

off 最后一轮控制器把 State ID 错填为 evidence ID，编辑被独立跳过，真实用户事件保持
pending，Host 仍正确回答 D-2/10:15。该轮为 1 degraded/1 pending，保留在主分母；on 为
0/0。这验证一次实际可选维护错误没有阻断业务回答，不代表全部降级情形均已验证。

## 因果边界与决定

H1（本例获得支持）：摘要漏掉精确对象身份，合法原始回执可以补足；实际 get 的参数
与回执一致且 found。H2（仍未排除）：Host 的独立参数理解与在线轨迹差异也影响结果；
两臂在生成 State 时已经有文字差异，并非同 bank 的严格替换。

这是一次暴露样本的完整配对，不是重复、unseen 或稳定收益。最初的错误 key、未引用
来源以及被保留的错误状态仍存在；不能把本次恢复成功写成全部 P1 已通过。

决定：**保留这条小型来源展开能力，推进强 G/L 的实现与少量 wiring**。两臂共同使用
相同引用解析、来源预算、事件权限和维护机会，只比较单个全局笔记与多个局部 State。
初步配对不要求所有旧 Host 精确键失误先消失，但不启动 36 条广泛批次，不宣称 LRU
候选缩减或 P3 已完成。来源控制合同不再追加措辞；空 focus 是另一独立候选。

## 成本与复现

| 角色 | 来源 on calls/tokens | 来源 off calls/tokens |
| --- | ---: | ---: |
| state_control | 10 / 11508 | 10 / 11086 |
| task_host | 10 / 13486 | 10 / 10782 |
| embedding | 1 / 44 | 1 / 44 |

生成总 tokens 为 24994 对 21868；on 多 3126（约14.3%）。其中既有来源展示开销，也有
不同 State/模型输出，不能把整段差值都分配给来源块。HTTP wall：control 30.585 秒，
Host 10.614 秒，embedding 0.326 秒；这是累计调用耗时，不是完整任务墙钟时间。

本批新增 **40 generation / 46862 generation tokens / 88 embedding tokens**。
连续账本 **1119 generation calls / 1347149 generation tokens / 10919 embedding tokens**。
LSA 启动以来累计 256 generation / 304420 generation tokens / 1302 embedding tokens。
unknown usage 为 0，历史账本及所有失败不清零。

实际 Store get 为 on105/off80，search 各101，put 为39/37。on 的12次引用解析各读取
tombstone及原事件，贡献24次get，已经包含于105内，不再重复相加。State逻辑正文对象
存储为2523/2085字节，事件为5321/5160字节；其他CPU/wall/逻辑读写字节见精简结果。
它们不是物理Postgres行、索引、WAL或完整checkpoint大小。

原证据在 ignored `artifacts/local-state-attention/p1-r5/`：实际入口 manifest、freeze、
run_plan、config、账本、逐 phase 结果与 Store 快照、trace、原 world/journal/checkpoint。
复现时固定本页提交和原输入，为两臂创建新 run/root，依次 prepare、run-phase 0/1；
不能覆盖旧身份。38项窄测、目标静态检查、两个零模型prepare和一次build已在运行前
完成；未为发布重复测试。Product 仍 NO-GO，完整 Goal 保持 ACTIVE。
