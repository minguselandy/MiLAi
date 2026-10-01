# v13.2 触发身份与支持来源的通用修复方案

只读方案已验收，并授权在87f74c6基线的新隔离树实施默认关闭`memory_support_contract=direct_support_v1`；必须显式使用event_bound_v1/read_handle_v1。实现与模型运行尚未验收。此前R5仍为24任务通过、7直接来源缺口，完整来源门槛未过。设计、原命令/hash、冻结澄清和授权范围见[只读验收索引](../data/manifests/v13-2-direct-support-design-acceptance.json)。

程序从实际Human事件绑定public-turn trigger，保留原Source ID/body hash、owner/bank/session、实际message ID及冻结profile/config。模型选择真实支持叶子；它们可以来自当前或历史，trigger无须出现在支持表。省略支持列表拒绝，不能默认最后/当前事件。角色/hash/owner、有限工具回执、实际读句柄和当前revision CAS继续验证。Source存在、ID可见、全文送达和语义支持分别报告；不增加语义蕴含verifier。

整字段复用只在模型显式选择实际candidate handle、按原patch规则构造新值后成立。content按完整UTF-8字节，scope/kind/basis按原service._json字节比较；不做strip、NFC、同义化或Python宽松bool/数值比较。复用的read revision/version hash和叶子绑定在commit锁内再次验证。旧版本无field map时只可带出模型明确选取的完整legacy_whole_version_set，标明它没有子句细分归因。改写字段必须显式选择真实叶子，不自动union旧来源或推断任意未改子句；正文语义仍unchecked。

trigger与模型支持/复用请求进入原proposal replay身份。相同ID/相同原请求返回原回执，改变trigger/candidate/支持请求冲突；历史读句柄不能代替当前CAS。成功Host提交按实际trigger查找，不能用支持表包含userRef判断；它只证明这一提交发生在本轮，不证明全轮内容已覆盖。由此减少的维护机会属于明确cadence因子，保留原跳过策略限制，不能归因纯来源表示。没有成功Host回执的query仍可维护，不按问题文本禁用。

实际Source.object_ref仍是完整VerifiedObjectRef DTO，manage_memory参数仍为string/null。在新profile中，仅对同一真实选中Source增加清楚命名的tool_argument_ids.object_ref字面ID投影，模型仍须选择Source/对象。dict仍是参数错误，不自动coerce，不改变JSON-action grammar或造新对象。所有新增trigger/支持/复用/伴随ID metadata进入原token计量；2048/6、排序选择、prefix/省略和read_more合同保持，不偷偷增送历史正文或免费读取。

Root核对41索引回执、39完整原before/after maps、四失败、12源码/文档快照、11已曝光R5 trace及17原请求对，复制262原产物。两恢复回执没有原after，其中shape检查也没有原before；晚期recovery map只表示后来观察，未知rg参数不补造。恢复时误猜chat_bridge路径的原receipt/第一版索引保留，并加独立勘误。design末句finite_checks.py为从未执行且已移除的草稿，冻结说明明确其PASS/机制测试为0；Root后来的missing-file读取记录另留。静态旧源码与原实际请求解释首次拒绝点，不是新修复已生效的证据。

实施将以禁socket的实际工具/recipe/invoke MockTransport与局部SQLite SDK验证等值/类型/Unicode、CAS与来源变动、owner/trigger/config、恢复/replay、Host-tool来源及object参数路径，再检查真实Qwen计数和默认wire/边界。默认行为与所有旧树保持；原失败/前后源码测试配置map须保存。模型实验须Root另冻新配置/源码/route/ledger/空root，继续原24/48与评分政策；旧输出不重跑、不拼接。没有独立评分、泛化、单因子收益或D4准入结论，Product保持NO_GO。

首次隔离压力显示新metadata会挤掉当前record及Source；原错误driver和修正后第一组交付退化保持，不作为成功。Root结合[固定Arrow20表示参考](V13_2_DESIGN_LITERATURE.md)进一步授权仅在direct_support_v1展示中以显式索引共享已有完整binding值，完整字段有序leaf/mode/reuse parent/version/field hash须严格可逆，所有表与说明计入同一2048/6。模型输入工具仍须实际string source_refs，不能自动索引coerce。若需compact helper，仅新profile路径可变；旧默认、存储、Source DTO、排序与选择保持。实际backlinks/current/history和超大材料须另测，联合表示及body allocation因子单列，源码与模型仍待验收。
