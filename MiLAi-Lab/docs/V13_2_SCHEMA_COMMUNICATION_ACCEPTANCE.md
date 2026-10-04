# 通用工具说明的限定工程验收

默认关闭的 `shape_feedback_v1` 已经 Root 有限验收，允许准备 R7。真实模型实验尚未开始，R6 的任务、来源与权限失败保持原结论，完整计划仍 ACTIVE，Product NO_GO。

Source `d6bb0a2` 从已发布范围 `8a9143f` 实现仅 7 个源码/3 个测试文件；Root 精确转入 `410e02f`。最终 212 runtime map 为 `36338eb57ba458ceb5a02308c254d84615f1896535c6a1e1c0a802c369e798cf`。Root 核验 1844 索引原件并复制 1853 文件，143 原回执/15 非零全部保留。Source 早期部分 inventories、bootstrap 缺原日志限制与分阶段身份均保留；48 PASS 原属 7a 阶段，最终 Source 11 入口检查另列。

最终主树 86 项受影响测试、7 源码 mypy、10 文件 ruff 与两个 boundary 通过。8 组默认目录/材料/请求/收据保持键顺序逐字节一致（仅排除计时字段），原错误请求/ToolMessage 字节也相同。Root 用独立 decoder 和真实本地 Qwen tokenizer 核验 6 压力包、完整请求成本；3 最终主树真实入口的 6 个 scripted Host/writer 请求与冻结目录、guide、原 schema SHA 对应。

新反馈仅投影已有异常，不重新验证或修改参数。保留真实 JSONSchema path/schema_path/keyword，严格公开 JSON 身份匹配才显示 expected；Pydantic 保留原 loc/type，Service 原原因不变。单份反馈上限 4096 UTF8 bytes，原路径/上下文身份及省略计数保留。原合成压力 64550 bytes/21680 feedback tokens 保留；修正后 3966 bytes/1864 tokens，合成完整请求 21717→1901 tokens，均不是模型样本。

| 原合成压力 | 实际材料变化 | Host prompt tokens | Writer prompt tokens |
| --- | --- | --- | --- |
| 短记录 | Source 前缀 195→39 bytes | 4345→5594 | 4362→5474 |
| 长记录 | 省略 Source 2→3；交付记录前缀变长 | 4347→5588 | 4364→5468 |
| 三记录/历史 | 历史/两个 Source 前缀 125/136/131→18/2/23 bytes | 4344→5593 | 4361→5473 |

原选择严格相同，普通材料仍≤2048/max6。新文字存在成本与正文交付退化，不能据结构反馈或 provenance membership 宣称语义蕴含、授权、质量或泛化收益。四种组合均保留完整 raw packets、selection、prefix/range/hash/omit；metadata/prefix 不算全读。

新 Root wire auditor 对原 R6 明确使用原 R6 SDK kind/arm，150 请求及48行原字段完全一致，原 rc1/三问题保持。最终新增路径通过9项合成 guards与上述6实际主树 mock-wire校验；默认 tool_mode 使用已有 json_action。所有原检查结果、导航失败、driver 版本与独立修正留存。原连续账本 SHA73c437ac 不变，新增 generation/embedding HTTP0。

下一步先冻结源码/配置/环境/真实路由/原rubric/连续预算并核对 GitHub，再首次运行原24轨迹/48消息、serial1。12/2048/6/writer1/repair0、旧 DTO/Source角色/hash/owner/CAS/权限与原生成 grammar 不变。独立 cap trace、共同四臂、HTTP 闭包、独立复核/第二模型/未见任务门禁仍未完成。

机器验收见 [manifest](../data/manifests/v13-2-schema-communication-acceptance.json)，设计见 [范围](V13_2_SCHEMA_COMMUNICATION_DESIGN.md)，已保存资料见 [论文与项目目录](V13_2_DESIGN_LITERATURE.md)。原件和运行日志保持本地 ignored，可分别从 artifacts/v13-2-schema-communication-source 与 artifacts/v13-2-schema-communication-integration 查看。
