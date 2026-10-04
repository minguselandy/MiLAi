# v13.2 通用参数说明、实际捕获效果与编码候选验收

Root 仅接受有限工程范围，未通过模型任务门禁。精确转移 Source 4e2f909 的 7 个 runtime 与 2 个 test 文件；Root 79 新控制、25 受影响旧控制通过，ruff/mypy、package/tools 两项边界通过。原 86 个方法字节保持，8 组 native/json_action × bridge/recipe × 缺省/显式 legacy 接口与回执一致，比较仅排除 material 的 CPU/墙钟计时，原计时留存。默认不启用新行为，Source 角色、hash、CAS、owner、选取与 allocator 不改。

A：tool_parameter_contract=explicit_shape_v1 只说明实际公开参数类型、正文 JSON 字符串关系、外层/字段 Source 成员与原版本守卫。B：observation_capture_feedback=typed_effect_v1 只包装已完成的 capture/projection 回执，pending 的确认数为 null；不新增 observe/get/read，也不确认语义写入或未来形成。两者独立 opt-in，不自动填 Source/修正文/重试/改最终答复。

C：compact_exact_v1 可严格恢复完整 DTO、顺序、标量和哈希；但 Root 合成公开 SDK 与固定 Qwen tokenizer 复核得到负面交付结果，下一实际配置不启用：

| 同一2048/max6条件 | compact_v1 | compact_exact_v1 |
| --- | --- | --- |
| 四条 Source 前缀正文总码点 | 222 | 131 |
| 当前/历史交付单元 | 1当前 + 1历史 | 1当前 |
| 实际选中冲突组 Source 前缀 | 355 | 60 |
| Source 去正文后重编码元数据反事实 tokens | 1977 | 1999 |
| 历史去正文后重编码元数据反事实 tokens | 1915 | 2002 |
| 冲突去正文后重编码元数据反事实 tokens | 1881 | 1986 |

元数据反事实并非可加 token 比例，且不含外层 HEADER；完整普通材料含 header/字典/布局/说明。选取完整 unit 身份及内容相同，交付因成本发生变化；冲突两组各两个候选均仅 stub，没有实际读完候选正文。A/B 四设置整模板成本 2567/3258/3041/3732 tokens，完整 HTTP JSON 3448/4141/3926/4619；不能隐藏说明开销。Mock usage 是脚本记账，非模型计算或质量证据。固定 Apache Arrow 20.0.0 原件与本次原浏览、阅读范围、中文负面成本反思保存在资料目录。

Source 113 原始 subprocess 回执、23 非零及一次未 dispatch 的 duplicate-label 控制器失败保持；后者缺当时 maps 明示不可得。Source 79 在最终 runtime、较早测试 map 上执行，随后仅合成冲突公开请求/选中组断言改动复跑 2 项并做 AST 同一格式化；Root 本次 79 在最终测试 map 执行。Root 另有三次核验/收口脚本错误：首次把方法哈希当作含缩进/装饰器/换行的整段哈希，第二次未排除材料计时；另一次收口 glob 将 pytest 的 current 目录别名计为额外压力文件；三次原件和实际失败后 maps 保留，恢复另存。它们不是 Source/model 失败。

实际 SqliteStore/SQLite 关闭重开与有限 fact/marker 写入切断控制通过，不能证明 SDK 构造返回前内部资源绝对闭合，也不构成 Store 多条写入事务/CAS。0真实生成/embedding，连续账本8547f1ef不变；旧R8/E2已封存索引逐hash复核。完整计划 ACTIVE、原48行不改、E0 NOT_PASSED、D4 NOT_ADMITTED、Product NO_GO。

[机器验收与原件索引](../data/manifests/v13-2-public-contract-engineering-acceptance.json)。下一步按原三种身份/更新接口另立共同 A 条件，B 暂不作为身份实验因素、C 禁用；先冻结和发布再执行新的 E2 自由模型切片，不能覆盖旧结果或称工程检查为独立 Judge。
