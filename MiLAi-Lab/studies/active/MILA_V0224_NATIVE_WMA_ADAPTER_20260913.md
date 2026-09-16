# V0224：WMA 原生 QA 最小接线

本次沿用户的“执行 v0.4”和“judge使用vllm”指令，冻结一套已下载 WMA 的四个开发 root、两个主要臂，按两根一波执行。运行合同为 [configs/v0224-native-wma.json](../../configs/v0224-native-wma.json)，原始记录位于 `/cra/memory/mx_memory/evidence/v0224/20260913-native-wma-v1`。当前 v4 冻结 SHA256：`73431de1d8c07bc396d1842d84f4ae7f80b03500b353c04d3c37eb5368d0f162`（v3 `fc0f75a16ccb098c22ccd2648ffe8b50e8ea81e0ece928b935f05f6fd7fe6e35` 保留）（v2 `6f5f4f2b112ea2a4d23ce9b7cd579535e9da6779b939ca59c911ec7ddfbd8182` 同样保留）；原 v1 `169b561f10286242153c5c1086a4c682923f090bd4aa5e65e558457ec385fb22` 保存在 raw `frozen-manifest.json`。最初规划的零额度由该有限合同替代；没有修改旧 Goal、Gate A 证书或暂停的 B–E 合同。

四根沿既有 V0217 personal 池的预定顺序选入 personal_18、personal_10、personal_01、personal_19，各完整保留 30 个会话、5 个原生 checkpoint、55 个问题及已有图片。每根是独立统计单位，220 个问题不等于 220 个独立 root。全部标开发暴露；未打开 reserve、candidate57 或确认集。

`B_native` 直接使用固定 revision 的官方 `MMFU_Single` adapter，按原生会话顺序导入允许的原文、时间和图片。保留官方正常历史能力及实际源码的 FIFO 上下文淘汰，按当前 vLLM 的 65536 context 配置，使用官方 GPT2 预算 tokenizer、8000 answer buffer、300 safety buffer、25 张历史图片上限、top_k=10，以及官方答题阶段的 5 张图片和 45 MiB 上限。真正发送前另用同一 vLLM `/tokenize` 核对请求长度，不截断任务补位。

`M_note` 将每个原生会话的标准化 turn 无损序列化，经普通公开 Note ADD 写入，再在原生 checkpoint 用公开分页 GET 取得累计历史；核对持久回执、版本、全文 digest 后，交给同一个官方 adapter。记录 `HARNESS_INGESTED`，不声称模型自主写入。当前四根各 30 次写入，正常路径分别需要 437、428、435、420 页 GET。只有同一个 checkpoint 内的实际读回内容可复用。四根使用不同的服务端认证主体，工具参数不能选择主体或 scope。

线上 reader 文件只含标准化历史、合法附件和问题。gold、evidence 标签及类别留在独立 evaluator 文件，答题进程不打开这些文件。离线 Judge 可以读取 reference answer 和官方 evidence 内容；它们不会回流答题。公开产品契约通过固定的本地安装使用，数据库、API、MCP 和主体均属于本次隔离实例，未修改 Product 行为或公开部署。

评价使用官方 QA 与 Evidence 原始提示词及官方 lexical F1/BLEU1 函数。答案和 Judge 均调用现有 `Qwen3.6-35B-A3B-FP8` vLLM，temperature=0、seed=2240401、关闭 thinking、答题 max_tokens=1024；Judge 初始为 1024，v2 放宽至 8192；这是用户授权的同模型评价，不是独立模型确认。Evidence Judge 与官方一样只接收检索文本，不能声称验证图片事实。没有测 session memory extraction/accuracy，故标 `NATIVE_TASK_LOCAL_ADAPTER / QA only`，不声称官方全榜复现。

必要差异仅有：本地有界 vLLM transport；替代会 gold 回退或吞异常的官方 answer factory；严格解析 Judge（不把缺标签自动计为 Omission，不补截断 JSON、不夹取无效 evidence 数字）；原生 session/checkpoint 循环将 reader 与 gold 分离；普通 Note 的机械 save/read 映射。原始上游文件未修改。真实请求、回复、失败、用量与耗时保留，不自动重试。包导入顺序先载入实际 tokenizer，避免上游可选 torch stub 误判 tokenizer 不可用；缺少的 tenacity 只补入本次独立环境，首次入口失败保留。

预设普通 review 仅在至少两根出现“B 正确、M 答案不同且不正确、官方文本 evidence 完全覆盖”的组合时触发，复用受影响原根全部问题的实际 M 输入、图片及草稿，增加一次固定普通复核。无新增根、无 gold 提示，不把触发本身解释为记忆固着；导入费用只记实际发生一次，review 的额外请求另列。

主比较最多 8 个完整单元；条件 review 最多 4 个。所有答案、Judge、4 个已知评分样例原 v1 合计最多 1988 次生成，v2 另加一次失败问题的 2 次评分调用，v3 再加第二根 5 个无效位置的最多 10 次评分，v4 再加首 Note 臂一条空白循环失败的最多 2 次评分，累计最多 2002 次；Provider HTTP 含两次身份读取最多 4006 次；Note 主任务最多 1856 HTTP，加主体隔离最多 28。累计 raw token 上限为空。模型请求 600 秒、Note 请求 60 秒、worker 4 小时、批次 24 小时是防挂保护，耗时不决定科学通过。未知用量停批；未知 ADD 只查一次 operation/status 后停止。费用未知不得记零。

本次只能回答原生 QA 的取得、呈现和答案差异。没有自主写 Note、动作世界、冷恢复或纠正窗口，相应指标为 N/A。第一批四根只支持可行性与开发决定；若两臂实际输入/答案一致或普通复核足够，保持简单，不另造 State 框架。

启动实测修订：Docker 默认地址池耗尽，改为本次独占网络的显式空闲 `10.244.224.0/24`，未修改或清理共享网络。首次 PostgreSQL TCP 可接时尚在初始化，迁移失败保留，待同容器 healthy 后继续；公开 MCP 启动器内部已经固定 `max-retries=0`，移除不支持的重复外层参数后启动。修订仅涉及本次服务启动环境和命令，冻结的答题、Judge、Note 数据路径均未改。隔离验证实际 24 HTTP、4 次 COMMITTED 写入及本人读回、4 次跨主体 `NOTE_NOT_FOUND` 均符合预期；这些辅助 Note 不进入任务读取列表。详细命令和失败见 raw `service/`。

Judge v2 修订：首根 B_native 的答案 55/55 完整，原评分 54/55 有效；`QA00:09` 的 Judge 输出达到 1024 token 而截断，原用量已知、原始回复保留。原阶段及父批次以 `JUDGE_PARTIAL` / `NATIVE_BATCH_FAILED` 真实结束。v2 仅放宽 Judge 输出上限，补此问题的两维评分，复用校准、55 个答案及 54 个有效评分；不重放成功位置。新评分追加到原日志，旧 invalid 仍可见，新终态带 `-v2` 后缀。零网络检验证明仅补缺失问题、保留原前缀和失败、实际调用上限为 2，且同时采用 8192 上限。

Judge v3 修订：第二根原评分终态为 50/55 有效、5 条格式无效，包括正常结束但 JSON 字符串未转义、evidence 字段计数不符合 schema。没有修补模型原文或把异常分配成 Omission。v3 使用 [vLLM 原生 JSON Schema 约束](https://docs.vllm.ai/en/latest/features/structured_outputs/) 请求官方原有字段、三类标签及合法 evidence 计数；只改变 Judge 输出结构约束，答题请求字节已用 MockTransport 验证与旧版一致。前两根 110 个答案、首根 55 个有效评分、第二根 50 个有效评分和既有校准均复用，只补 5 个问题位置。旧失败及其全部请求计费保留，新终态带 `-v3` 后缀。Judge 为组合版本评价，不宣称统一单批解码条件；确定性的原生 lexical 指标与实际输入、答案差异分列，格式修订引起的评分差异不得归因于 Note。

Judge v4 修订：首根 M_note 的 55 个答案完整、54 条评分有效；一条 Judge 在 JSON 字段间输出 7348 个 TAB，最终触及 8192 token 限制且缺少闭合结构。原截断原文、费用和 v3 失败终态保留。v4 使用 vLLM 原生 `structured_outputs.regex` 限定紧凑 JSON：原字段、合法 Unicode 和转义、原三类标签与合法计数，字段间不允许自由空白；解释字符串最多 1024 个合法字符或转义单位。它限制的是评分输出协议，不改变任务历史、答题请求或评价语义提示词。只有本条问题补两个评分调用；三个已完成答题单元及所有有效评分复用。25 项 mock/正则验证涵盖实际 TAB 故障、超长/截断、合法 Unicode/转义、原默认答题请求字节与账务。实际评分仍按组合版本、有限开发评价解释。
