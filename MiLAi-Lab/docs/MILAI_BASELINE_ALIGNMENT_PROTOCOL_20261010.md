# 本地基线对齐协议 v1

执行范围为计划 E0–E4 与现有 Host 连续流程；本卡记录新配置，不改变冻结 5019968。Root 负责公共合同、配置、串行资源与最终结果，三个开发者分别负责 RawRAG/Hindsight、MiLAi 纯记忆/交付、Host/结果。

| 项目 | 首轮共同条件 |
|---|---|
| 数据 | 既有 HaluMem-Medium 四开发用户前八会话，32 会话/73 QA/72 更新机会；不读保留用户 |
| 时间 | 每个独立后端/用户/重复按时间写入一会话，实际完成后仅答该会话问题；无未来来源 |
| 信息 | 现有 ObservedSession：session_id、公开 date、role/content/timestamp；source-only，无 persona/gold/更新标签 |
| 臂 | RawRAG-local、Hindsight-native-local-recall、MiLAi-memory-only；原生答案另列 |
| QA | 可计数后端请求 20 项；Hindsight 保留原 max_tokens 并记录实际数量，不称 K20 |
| 维护 | MiLAi 写入候选保持原 K10；QA20 显式传参，不改变维护池 |
| 更新评价 | 参考查询仅在冻结的只读会话视图，K10；不支持隔离或真实会话输出则 N/A |
| Reader | 既有 Qwen3.6-35B-A3B-FP8，temperature=1、output=32768、thinking=True、context=65536、margin=512；实际完整输入上限 32256 |
| 交付 | 首轮直接读取，无二次 Selector；staged 为独立因素，保留真实范围和缺答 |
| 来源 | 各后端按原生输出交付；原文与 retrieved_memory 分开。MiLAi 主臂采用实际语义状态及其已有支持，不增加独立原文搜索兜底 |
| 持久/隔离 | 各后端/用户/重复独立 bank；会话 ID 稳定，Hindsight document_id 对应会话；问题/答案不写回 |
| 失败/评分 | 逐题保存；已知只读缺答保留全部机会，unknown 不重试；三个后端预测结束后独立评分，原官方标签不改 |
| 费用/资源 | 原连续账本、Root 串行 Qwen/BGE/Judge；外部内部用量缺失记未观测，不填零 |

薄接口只需 ingest/retrieve/close。所有后端复用既有 ObservedSession 或结构等价的字段接口；retrieve 返回 materials（供 Reader 的原样文本/时间/实际 ID）、native_return（完整实际后端返回）、returned_count、source_mapping、usage。材料不经过额外抽取、摘要或 Selector；可选 session_output 仅来自实际会话原生输出。公共类型由 Root 管理。

调度：07:05:31 UTC 实际确认原五方法 PID1854770 运行、HTTP 租约占用，B0 89/277会话/219 QA检查点（217答案+2缺答），其余未开始。开发/离线检查可以并行；不启动新的真实模型调用、不热改旧运行。资源释放后新任务优先 E0/E1，无须将全部旧科研待办作为永久前置。

最新固定观察与当前开发范围见[现有报告](MILAI_UNIFIED_MEMORY_USAGE.md)。恢复维护K10后的新根准备
确认每臂32／73／72机会、12个独立bank标识，网络禁用且0实际模型；它不是最终确认冻结。
预测／评分成功终态在实际后端和原资源正常关闭后发布；已drained失败仍为FAILED，
闭合未知保留RESOURCE_UNSETTLED和原错误，Root确认原生服务停止或完成前不调度下一方法。

能力接通、机械检查和真实模型语义结果分别记录。四开发用户与共享 Host 故事用于描述性比较；独立性、费用和未完成项沿计划原样报告。
