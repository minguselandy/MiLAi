# D1 E2：回合快照在线小比较

2026-09-27。**四条轨迹已完成，实际Goal已按用户要求paused。** 源码
`0c5f027750eac1a45245d5a9ac43e48eb5e202e9`；[冻结协议](../data/manifests/local-state-attention-review-e2-sandbox-r1-protocol.json)
与[机器结果](../data/manifests/local-state-attention-review-e2-sandbox-r1-results.json)保留输入身份、分母和费用。
只完成当前切片，不开展E1或D2–D5。研究总目标未完成，Product NO-GO。

## 结果

| 已暴露脚本 | pre_model strict | turn_end strict | 完整轨迹 |
| --- | ---: | ---: | --- |
| 两个同文本、不同ID的加一事件 | 3/5 | 3/5 | 两组均0/1 |
| 双owner与部分成功后跨进程恢复 | 4/6 | 4/6 | 两组均0/1 |
| 合计 | **7/11** | **7/11** | **两组均0/2** |

22条消息正常结束，8个独立阶段进程全部退出成功，但四条轨迹均有语义失败。
两组distinct均在second-increment和final-action失败；两组partial均在partial-action和other-owner-action失败。
回合快照工程接线得到验证，**这次小样本没有显示strict质量改善**。

## 比较合同与实际执行

两组均为local_all_sources：相同原脚本、业务工具、owner权限、events-only维护生成器、全部State读取、来源展开预算、普通memory工具。
运行配置仅control.update_epoch不同；源码、原始输入、rubric、顺序、命名空间、模型参数先冻结。
顺序为distinct turn_end、distinct pre_model、partial pre_model、partial turn_end；每格一次，全部Root串行。
各组从原始用户信息独立形成State，没有注入正确bank。每轨迹两阶段用不同进程与实际持久化。

turn_end在公开回合开始把完整State正文存入现有Store/meta；同回合的Host请求固定展示它。
真实用户/工具prefix保持原样，回合内收集事件，正常/容量结束显式close。默认pre_model仍在每次Host前维护。
标签为已冻结的“Snapshot captured before the current public user turn.”，没有新增Host措辞补丁。
回合、合批、调用数量、形成内容和普通memory路径均可随之变化，故这是在线recipe比较，不能视为纯标签或A/U消融。
两组本切片都没有read_history工具；共享完整历史与强基线的后续matched仍未运行。

既有Host为Qwen3.6-35B-A3B-FP8，temperature0、max_tokens4096、thinking=false、context65536，
每消息Host最多12次；维护max_tokens2048、最多13次。Embedding为bge-m3/1024维；实际HTTP并发1。
/models只读核实后未调整任何共享服务。运行时没有读取rubric/gold。

## 完整证据链

- 37次真实Host HTTP的非system消息逐字匹配原始checkpoint经既有JSON-action传输转换后的prefix；37个State视图确实进入对应HTTP。
- 30次维护请求均无current_task，所有new_observations与持久化实际事件的ID、actor、tool_call_id、正文一致；每个事件恰好进入一次维护批次。
- turn_end捕获11个回合快照，18次Host交付在各自回合内正文完全稳定；阶段结束持久化的相应快照正文与视图一致。
- 11次close全部成功、pending清空；这只证明维护已执行。实际模型仍可能写错语义。
- 两个distinct独立事件正文相同、source ID不同，均被维护，未按文本去重。两组维护器都先正确形成2→3→4。
- 两个partial轨迹实际均只有2次reserve与1次complete_label。Mira的ok=false保留真实预约ID和not_created；新进程真实get found，再用同一ID完成标签，没有重复reserve。
- Noel沿自己的2/south bay S-8/cloth covers行动，Mira的D-2/10:15保留；没有跨owner事实/ID串用。
- 所有HTTP响应文本、receipt、usage、冻结源码/配置/输入哈希与连续账本相符。观察者和业务journal/数据库大小、方法Store逻辑I/O另记。

本批没有自然发生容量终止、close失败、同回合进程崩溃或未知副作用。相关模拟HTTP/真实SQLite局部检查只作工程证据，不冒充真实模型恢复实验。

## 失败、解释与决策

### 1. distinct：时点改变没有保证Host正确消费

**Observed：** pre_model第二次增量先把State正确从3改4，随后Host却提议普通memory写5，使用虚构非UUID的memory_id_from_previous_state，工具返回局部验证错误。
错误ToolMessage原样包含提议的5；下一次维护把5写入State，之后Host创建普通memory并最终实际预约5。
不是HTTP错误：失败发生在普通memory参数验证与语义消费层。工具错误和后续调用均保留/计费。

turn_end第二次增量实际接收到旧State3和新加一，却把旧用户message UUID误用为普通memory ID，写入3并回答3。
observer证明这次update实际插入了新memory，不能把“updated memory”回执理解为正确修订了原memory。
随后close把State正确改4；final-action真实HTTP已有正确State4，但同session助手历史仍是3，最终预约3。
最终两组destination均为S-2，而冻结业务字段为storage S-2。turn_end最终回答还将实际S-2报为storage S-2。

**Expected：** 两个独立加一分别生效，回答及唯一实际预约quantity4、完整item_key、destination storage S-2、fiber cases，并忠实报告回执。
**首断点：** 第二次增量Host的普通memory提案；final-action是错误继续传播。此前两个事件及维护数值正确。

**竞争解释：** H1，pre_model把已更新4当作旧基数再加一；H2，Host使用旧来源/助手答案或普通memory身份混淆，覆盖当前State，turn_end同样存在。
前序条件诊断支持H1可能发生，但本在线失败说明时间边界并不足够，不能断言全部由H1解释。
旧来源中原2、当前3、工具/assistant文本及新事件共同存在；此批未独立交换这些因素。

**最小候选与下一实验（暂停，未执行）：** 固定本次合法前缀，分开去除普通memory双写机会和调整来源消费范围，保持相同当前信息/工具权限对照；检验正确State与旧助手冲突时的真实动作。
不用答案规则修数量、不新增语义审核器，不再做无目标措辞循环。
**决定：Pivot诊断消费层；保留可选快照实现，不声称已解决增量。**

### 2. partial：同ID恢复成功，精确对象key仍错

**Observed：** 两组Mira/Noel实际reserve均把Summit archive crates改单数Summit archive crate；数量、地点、包装正确。
初始State正文保留复数，但title已经是单数，两者同时进入Host，因此首个表示偏差在formation title，真正业务错误发生于Host参数。
真实get/complete_label沿最初错误key生成的实际ID完成，恢复通过不追补两次初次key失败。
两组回答均忠实报告部分成功，恢复未推断physical dispatch。turn_end的“以后服务恢复时重试标签”没有在本回合实际重试。

**Expected：** 预约key逐字保留完整复数；部分副作用和恢复维持真实ID、scope与回执。
**竞争解释：** H1，单数State title对Host参数形成诱导；H2，Host自身词形归一化，即使正文和当前用户仍是正确复数也改名。
本批没有独立替换title，无法区分。pre_model还曾把已创建预约概括为“failed / No business action has been completed successfully”，但正文同时保留ID和not_created；turn_end回执维护更明确，此单次差异不是总体语义增益。

**最小候选与下一实验（暂停，未执行）：** 在相同合法前缀固定正文、仅替换生成title为原始完整引用，比较实际参数，辅以无State原prefix控制；若无效，直接定位Host的参数生成。
**决定：保留部分失败恢复工程路径，精确身份缺陷继续开放。**

### 评分边界

沿前序条件报告边界，first-read自然语言“to be stored in S-2”视为同一storage S-2地点，故通过；实际业务API destination必须精确等于storage S-2。
这是自然语言回答和结构化字段的不同合同，不放宽实际动作。复数业务key不接受单数替代。
恢复答案不必重复ID字符串，但实际get和complete_label必须使用真实原ID；两组均满足。

## 全成本

| 费用 | pre_model | turn_end |
| --- | ---: | ---: |
| Host调用 / tokens | 19 /32134 | 18 /21072 |
| 维护调用 / tokens | 19 /22319 | 11 /11967 |
| 全生成调用 / tokens | **38 /54453** | **29 /33039** |
| Embedding调用 / tokens | 3 /211 | 3 /90 |
| 生成HTTP墙钟秒 | 47.916 | 23.994 |
| 方法Store get/search/put调用 | 280 /172 /75 | 315 /114 /69 |
| 方法Store请求/返回逻辑字节 | 134062 /315983 | 127158 /222398 |
| 新增快照正文累计字节 | 0 | 6235 |
| close新增checkpoint读取 / 逻辑字节 | 0 /0 | 11 /26382 |

此批turn_end生成tokens少21414（39.33%），两个strict分数相同。两组普通memory路径、维护次数、正文长度及错误历史不同，不能归因于压缩或纯快照存储，也不是稳定成本结论。
Host/control/embedding的HTTP墙钟分别在机器清单中保留，不等于完整进程时长或硬件费用。
Store数为方法API调用及逻辑字节，不能冒充底层磁盘/网络物理I/O。

普通memory成功写入两组各3次；pre_model另有1次无效ID工具调用。实际insert/update、observer事务/CPU/墙钟、额外Store读取两组各6次、SQLite/业务文件大小均单列。
Root额外观察为8次空namespace预检和8次阶段后Store快照search，无embedding；离线checkpoint读为评分成本，未混成方法runtime。
没有伪造尚未测量的底层磁盘I/O、峰值内存、价格或GPU摊销。

本批新增**67次生成 /87492 generation tokens /301 embedding tokens**；连续账本最终
**2768 /3420333 /18746**，usage均已知，旧sealed history完全保留。
账本SHA256：`a9d4c681e2bee395c170a4672b4895a442522df47951c9a043e9f6b3a32e3580`。
D0无新增模型调用；本次复盘含此前条件诊断共91次生成/123542tokens/301embedding。

## 检查与复现

源码交付17项相邻检查通过，最后边界修改后7项turn_end检查通过（有重叠，不相加）；目标Ruff/Mypy、4次零模型prepare及必要构建通过。
Root另作实际运行prepare冻结，非重复发布测试。没有源码变更或参数扫描穿插在批次内。

在上述commit的MiLAi-Lab中使用既有锁与环境。复制configs/local-state-attention.json到ignored runtime目录，仅设置capacity.tokenizer_path为本机相同tokenizer，control.update_epoch为相应条件。
实际配置SHA见机器结果绑定的原run manifest/冻结记录；原始输入及rubric哈希见协议。
私密DSN通过MILAI_LANGMEM_POSTGRES_DSN注入，不输出。以下是单组命令结构；复现须另获继续授权，使用全新run/root而非覆盖原结果：

```bash
uv run --no-sync --group baseline-langmem python tools/run_local_state_attention.py prepare \
  --config "$MILAI_CONFIG_PATH" --script "$MILAI_SCRIPT_PATH" --run "$MILAI_RUN_ID" \
  --arm local_all_sources --repeat 1 --runtime-root "$MILAI_RUNTIME_ROOT" \
  --output "$MILAI_RUNTIME_ROOT/prepared.json"
uv run --no-sync --group baseline-langmem python tools/run_local_state_attention.py run-phase \
  --config "$MILAI_CONFIG_PATH" --script "$MILAI_SCRIPT_PATH" --run "$MILAI_RUN_ID" \
  --arm local_all_sources --repeat 1 --runtime-root "$MILAI_RUNTIME_ROOT" \
  --prepared "$MILAI_RUNTIME_ROOT/prepared.json" --phase 0 --stage lsa-review-e2-sandbox-r1
```

阶段1使用相同参数和--phase 1，由新的独立进程执行；按协议顺序完成四组。成本连续累计。
原始私密轨迹、数据库、DSN、环境和构建产物不提交；公开源码、协议、精简结果和本文足以定位每个冻结批次。
本次收尾后的完整未完成项与暂停边界见[总体报告](MILAI_LSA_REVIEW_OVERALL_EXPERIMENT_REPORT_20260927.md)。
