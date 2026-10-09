# 统一记忆功能候选与当前执行状态

当前按用户提供的[全局修复与功能优先规划](MILAI_GLOBAL_REPAIR_AND_FUNCTION_FIRST_PLAN_20261009.md)
执行，候选为 `milai-global-function-first-v1`，集成分支为
`feat/lab-global-function-first-20261009`。工程修改已合流，真实 Host20 尚未开始。
旧失败、费用和历次运行观察完整保留在[历史状态页](MILAI_UNIFIED_MEMORY_USAGE_HISTORY_THROUGH_20261009.md)，
其中“RUNNING”均为原时点快照，不作为当前进程状态。

## 当前实现与入口

一个配置文件 `configs/milai-global-function-first-v1.json` 提供 functional 和 benchmark
两个入口。Host 维持原 JSON v9 当前请求、staged/record、8192 输出、24 次消息调用额度；
benchmark 维持 staged/record_units、K10、65536 上下文、32768 输出、512 余量。
两入口共用既有 Qwen3.6/BGE 服务和原连续账本，保持各自原来的读取权限。

- `memory/reader_projection.py` 是纯投影。实际单元替代整版正文必须有精确渲染证明；
  不可证明时保留正文。重复完整元数据共用一张单层表，不推断缺失信息或继承默认值。
  benchmark 的原 `revision_evidence` 正文和范围仍直接交付；Host 保持原文和历史工具。
- 完整请求容量使用部署的真实 Qwen 模板和阶段 thinking。逐条成本只作提示，
  联合容量另算。超限保留全部所选引用、未交付状态及整事项页面计划；
  benchmark 当前不执行该页面计划，已知 HTTP 前超限记录缺答后继续自然历史。
- 已确认 CURRENT 业务 schema 失败时，只有独立明确的当前保存范围才继续记忆工作，
  业务分支不取得执行许可。纯保存恢复不发现或重办业务；当前只读不继承旧写权限。
- 完成信息累积实际保存回执，每个已返回批次立即进入 trace；原文捕获、语义提交、
  未完成业务和遗忘分项表达。原始模型答案与程序附加反馈分别保存。
- Extractor/Editor 保留考虑、愿望、计划、说话者与主体；候选仅作线索，Source 才是依据。
  既有引用 keep、原文 Episode 和局部算子继续复用。

正常使用入口示例（从 MiLAi-Lab 执行；不包含自动模型派发）：

```bash
PYTHONPATH=src python tools/run_functional.py prepare \
  --config configs/milai-global-function-first-v1.json \
  --root artifacts/global-function-first/personal
PYTHONPATH=src python tools/run_functional.py message \
  --root artifacts/global-function-first/personal --bank personal --owner example \
  --session example --message-id save-1 --text '请记住，我的午休提醒用静音模式。'
```

第一条只 prepare；第二条是真实功能调用，会使用现有服务和账本。原实验配置与
默认 fail-fast 保持兼容，不把旧请求重新解释成新策略。

## 已闭合验证与旧实验

原失败八事项经实际 Qwen thinking 模板、原问题和 read_goal 独立复算：
**32446 → 30520 input tokens，限额仍为 32256**。8/8 有整版渲染证明，
56 个单元、39 段原证据正文/范围、14 项正条件及562项时间字段通过还原核对。
这是 0 HTTP 的容量和材料检查，不是新模型语义结果。

旧 M36 (`36b0401`) 仍为 FAILED：21 个完整会话预测/46 答案，末会话另有2个实际响应，
qa2 在 HTTP 前因32446输入终止。22份维护结果中17 completed/5 incomplete，
43去重提交、6 current_boundary_source_required 拒绝。旧数据不补成新候选轨迹。
旧闭合成本为162生成/1748782 known tokens、140 encoder/18648 tokens，新增unknown0。
原全局账本固定闭合值49574请求/227101922 known/227378618 charged、2042879 embedding，
历史 generation unknown6；不重置或把后续实时账本差额误记成旧 M 成本。

本次集成后29项受影响正常 SQLite/模拟 HTTP 检查通过；受影响文件 Ruff、严格类型检查
及 package/tools 依赖边界通过。检查记录在本地 ignored 验证产物中保存。
模拟调用不计真实模型样本，也不宣称完整仓库或远端 Full 通过。

## 下一项工作与仍未完成范围

先冻结本候选，再让原三链20消息从各自空库真实运行，保留实际限制和原恢复control。
工程错误与普通语义失败分别定位；unknown HTTP、未知写入/业务效果和 Store 故障停止相关路径，
不盲重试。新 benchmark 预先声明按题保存成功及已知只读缺答，缺答保留在全部机会分母。

随后四开发用户集中前缀及统一评分；最终仍需同版五方法各277会话（合计1385）、
原 native32/12会话/4用户、drift/recovery、必要 M 消融与紧预算、最终冻结后的16保留用户、
LongMemEval、RawRAG/RollingSummary/A-MEM真实适配，以及 Host135case/192message 和新故事。
六项最终交付和方法选择均未完成，Product 仍为 NO_GO。工程可用、模型语义与科研优势分开判断。
