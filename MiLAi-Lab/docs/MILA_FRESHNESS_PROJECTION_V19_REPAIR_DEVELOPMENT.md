# v19 修复开发记录

执行用户 [v19修复.md](v19修复.md) 共747行，SHA `2b5e9c4f106ffbc721ec4d9dcf0dba14229b742e044edf5a29f21b0a2c2b4c27`；原文保持不变。执行范围与顺序见[Goal](MILA_FRESHNESS_PROJECTION_V19_REPAIR_GOAL.md)。

## A1：先使用未改源码的 Notice

参考提交 `d0367aab36c15b39bdd4e2c1fd7a92a542f66fcf`，52文件mapping `1f22b6b7b032a647e360c140c61467763f7ce71b0a1fdd481d1c00ede88fbfaa`。在任何源码变更前，完成原source/validation核对、原vLLM container/image/command/environment/HostConfig核对、新独立账本、三组空namespace及zero-model prepare，并形成[reference](../data/manifests/freshness-v19-repair-reference.json)和[A1 freeze](../data/manifests/freshness-v19-repair-a1-freeze.json)。新授权允许这次原先被v19 gate关闭的F-only运行，不改旧结果/旧gate的历史记录。

三个原fixture、原工具、原B1 schema与现成freshness_only合同完全沿用；没有ODR protocol、reconstruction字段或handle目录，也没有新增探针。所有真实请求由Root串行执行。

| 例 | 初始search | 更新后search | 获批动作 | 判定 |
| --- | ---: | ---: | --- | --- |
| changed | 1，真实X@1 | 0 | 4°C | FAIL |
| retained | 1，真实X@1 | 0 | 8°C但未取X@2 | FAIL |
| irrelevant | 1，同时返回X和Y | 0 | 8°C | PASS |

每例3条公开消息、5次生成，均完成。实际Provider request证实每例3次notice同时仍有完整旧ToolMessage正文；changed业务前两个request看到stale提示仍使用旧4。全部费用15生成／13604tokens／270embeddingtokens，unknown/截断/Judge均0。详见[A1结果](../data/manifests/freshness-v19-repair-a1-results.json)。移除ODR结构负担没有促成重新取证，因此进入A2。

## A2：设计前置约定

只在Provider request副本中把SUPERSEDED/DELETED搜索项的旧正文替换为机械marker，CURRENT/UNKNOWN项和数组次序不变；原ToolMessage、assistant历史、checkpoint和Store保留。新短source-authority原则说明旧assistant说法不能作为当前动作参数的权威证据，不追踪其命题。

这是“逐项隔离＋通用authority原则”的组合干预；A1仍是原未改合同，不把差异归因成纯renderer效果。A2不读取当前版本、不自动search、不加response schema或业务真值gate。若A2不足，才实现同对象public Store.get的A3；不得提前隐藏加入刷新。

原B1只把body_ref完全一致的ToolMessage记FULL。投影后应使用明确PROJECTED_WITHHELD身份，并在实际Provider body和原search source都匹配时绑定；不能继续把隔离前全文记为已交付。逐项projection plan/event保留ref、状态、source call、位置、body是否交付等机械信息，供离线判定。它不构成持续语义State或新数据库。

旧M1断言漂移另行仅修测试期望，保留v18运行行为；不将其与freshness成败混合。源码由同一Sol xhigh负责，Root继续独占真实模型请求、冻结与报告。原始trace/DB/私密配置留在ignored artifacts。

## A2 验证、运行与后续 gate

受影响25条窄测通过，最终两条新投影测试通过；旧M1期望漂移分支另独立1条通过。ruff、11文件mypy、两项边界检查通过。新测试实际经过LangGraph、observer、SQLite checkpoint和mock Provider，覆盖mixed CURRENT/SUPERSEDED/DELETED/UNKNOWN、同文新版本、不同namespace同key、原assistant保留和completed replay。新schema与A1实际request的schema完全一致，不补复制式decoder probe。

A2冻结59文件mapping `03c8923a0069b53ca6fe516fd89b882a14e0aa20bce68aca6ddb824932304460`，lock SHA `398669b26e9bd26a9b909f9920ab5525972377602f46d21b9ab97b1311395c27`。三组新空namespace和配置在真实请求前冻结，见[A2 freeze](../data/manifests/freshness-v19-repair-a2-freeze.json)。包装声明已扩展，但build等最终级别后只做一次。

三个小例均完成3条公开消息、5次生成。9个request的旧item正文确实被替换，actual Provider body与PROJECTED_WITHHELD记录一致；原checkpoint ToolMessage保留，current项及顺序不变，旧assistant结论仍在历史。自动exact读取为0、更新后search为0。

Changed仍实际记录4°C；retained记录8°C但未读取X@2；irrelevant正确8°C且无额外search。因此A2仍为1/3，通过的是irrelevant，不能把旧正文隔离成功当作行为修复成功。费用15次／13954tokens／268embeddingtokens，unknown/截断/Judge为0。完整逐请求核对见[A2结果](../data/manifests/freshness-v19-repair-a2-results.json)。

这支持按原顺序进入A3 exact refresh，而不是强化重建schema或改变vLLM。A3保持A2的authority原则和响应合同，唯一新增机制是解析即将进入request的同一过期对象的当前版本。先由Luna建立A2本地源码/证据commit作为可复现点，再改相同文件；最终全部完成后统一推送。
