# 统一记忆功能候选与当前执行状态

当前按用户提供的[全局修复与功能优先规划](MILAI_GLOBAL_REPAIR_AND_FUNCTION_FIRST_PLAN_20261009.md)
执行，集成分支为 `feat/lab-global-function-first-20261009`。第一版源码 `bbe77e9`
的真实 Host20 已闭合；修复候选 `milai-global-function-first-v2` 冻结源码为 `1cfb400`。
原Host20新空库运行在2026-10-09 17:56:46 UTC停止：13 COMPLETED、7 NOT_RUN。
两次遗忘拒绝回执缺少effect字段，汇总保守标成unknown；独立代码边界及只读数据库核对
确认仅这两次属于写入前无效果拒绝，原STOPPED结果保持原样。18:04:32 UTC启动单独补充运行，
仅处理尚未尝试的7条新输入，仍使用同一冻结源码，已于18:11:41 UTC闭合：5 COMPLETED、2 FAILED。
原20条输入各尝试一次，分段总计18 COMPLETED、2 FAILED。四用户前缀M于18:14 UTC启动，
PID667365，源码仍为`1cfb400`，输出`artifacts/global-function-first/prefix8-1cfb400-v2/M`，尚未闭合。
实际结果位于 ignored `artifacts/global-function-first/host20-1cfb400-v2`，原运行与补充运行
各自保留execution/results/accounting；调度前核对实际终态与PID。
旧失败、费用和历次运行观察完整保留在[历史状态页](MILAI_UNIFIED_MEMORY_USAGE_HISTORY_THROUGH_20261009.md)，
其中“RUNNING”均为原时点快照，不作为当前进程状态。

## 当前实现与入口

当前一个配置文件 `configs/milai-global-function-first.json` 提供 functional 和 benchmark
两个入口。Host 维持原 JSON v9 当前请求、staged/record、8192 输出、24 次消息调用额度；
benchmark 维持 staged/record_units、K10、65536 上下文、32768 输出、512 余量。
两入口共用既有 Qwen3.6/BGE 服务和原连续账本，保持各自原来的读取权限。

- `memory/reader_projection.py` 是纯投影。实际单元替代整版正文必须有精确渲染证明；
  不可证明时保留正文。重复完整元数据共用一张单层表，不推断缺失信息或继承默认值。
  benchmark 的原 `revision_evidence` 正文和范围仍直接交付；Host 保持原文和历史工具。
- 完整请求容量使用部署的真实 Qwen 模板和阶段 thinking。逐条成本只作提示，
  联合容量另算。超限保留全部所选引用、未交付状态及整事项页面计划；
  benchmark 当前不执行该页面计划，已知 HTTP 前超限记录缺答后继续自然历史。
- 已确认 CURRENT 业务 schema 或 length 失败且用量已知时，只有独立明确的当前保存范围才继续记忆工作，
  业务分支不取得执行许可。纯保存恢复不发现或重办业务；当前只读不继承旧写权限。
- 完成信息累积实际保存回执，每个已返回批次立即进入 trace；原文捕获、语义提交、
  未完成业务和遗忘分项表达。原始模型答案与程序附加反馈分别保存。
- Extractor/Editor 保留考虑、愿望、计划、说话者与主体；候选仅作线索，Source 才是依据。
  既有引用 keep、原文 Episode 和局部算子继续复用。

正常使用入口示例（从 MiLAi-Lab 执行；使用已安装的Lab环境）：

```bash
MILAI_PYTHON=/cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python
PYTHONPATH=src "$MILAI_PYTHON" tools/run_functional.py \
  --runtime-dir artifacts/global-function-first/personal-runtime prepare \
  --config configs/milai-global-function-first.json \
  --root artifacts/global-function-first/personal
PYTHONPATH=src "$MILAI_PYTHON" tools/run_functional.py \
  --runtime-dir artifacts/global-function-first/personal-runtime message \
  --root artifacts/global-function-first/personal --bank personal --owner example \
  --session example --message-id save-1 --text '请记住，我的午休提醒用静音模式。'
```

解释器路径可替换为已安装Lab依赖的环境。runtime目录在导入SQLite等模块前设定；
当前机器的系统`python`不可用、默认临时盘已满，工作树复用原checkout的`.venv`。
prepare只准备；message是真实功能调用，会使用现有服务和账本。原实验配置与
默认 fail-fast 保持兼容，不把旧请求重新解释成新策略。

## 已闭合验证与旧实验

原失败八事项经实际 Qwen thinking 模板、原问题和 read_goal 独立复算：
**32446 → 30520 input tokens，限额仍为 32256**。8/8 有整版渲染证明，
56 个单元、39 段原证据正文/范围、14 项正条件及562项时间字段通过还原核对。
该材料检查为 0 HTTP。另在第一版冻结源码上执行一次真实只读 Reader：
正式 stop，实际输入30520，输出2166（含thinking），合计32686 known/charged；
0 embedding、0 Judge、新unknown0。原始模型答案已保存，语义正确性尚未统一评分。

第一版原三链20消息在2026-10-09 17:19:01 UTC闭合，20/20实际尝试，
17 COMPLETED / 3 FAILED。逐响应核对为99 generation / 784557 known=charged，
35 embedding / 1532 tokens；stop53、tool_calls44、length2，新unknown0，Judge0。
fixture/control不变，每个新消息单独CLI进程；失败消息未重试，旧运行未热改。

| 原链 | 结构完成 | 真实断点与范围 |
|---|---:|---|
| 保存、切换、重开6消息 | 6/6 | 两项实际保存，后续只读无语义或业务写入；不据此推出完整语义验收 |
| 更正、历史、遗忘8消息 | 6/8 | 两次确认length；Editor首次补造起效日期、漏改明确通知值；Reader错误继承未规定分组频率、误解查询缺失 |
| 业务、结果保存、遗忘6消息 | 5/6 | 首请求在多余旧请求解析阶段schema失败、尚无业务效果；故未验证原本的部分业务续办链。后续确实撤销8个来源可见性 |

更正链当前读第一页实际送4/5单元，第5加入后约8922>8192；首单元已送达，
历史17项确为三个版本5+7+5语义单元。共用元数据补丁的完整当前页为6593/6587，
历史首版完整5单元为6027/6020，均包含表及说明；历史仍需分页。零HTTP还原检查保持所有字段，
不改变页额度、正文、范围、实际选择器或原文权限。
当前补丁还处理已知截断的独立保存、无issued旧请求时的确定空选择，以及真实保存回执反馈。
Source提示将明确值与实际状态比对，未知起效日期保持未知。第二版前13条实际调用为
71 generation / 565201 known=charged、1246 embedding tokens、新unknown0、Judge0。
补充段另31 generation / 336871 known=charged、610 embedding tokens。合计逐响应核对为
102 generation / 902072 known=charged、50 embedding / 1856 tokens；stop61、tool_calls39、length2，
新增unknown0、Judge0，原停止和补充终态分别保留。更正链首次仍补造季度日期并被拒绝；
后续明确通知值实际提交，但Reader仍把整体频率
错误赋给未单独规定的分组。有效遗忘实际撤销一个事项及9个来源；未形成事项的初始Source
仍可见，不能据此宣称全部关联原话已遗忘。补充链已实际形成一次部分预订和一次单独补标签，
只有一份预订、两次业务尝试；其纯保存请求却被CURRENT误解成业务续办，未取得保存许可。
业务遗忘在已确认length前提交r3语义撤销，未调用forget_memory或撤销可见性；原话/历史仍可读。
重开模型把retracted误报成已清除，不能算成功遗忘。上述普通语义
失败保留，不以COMPLETED冒充验收。原始答案和附加回执分存；前表费用仍仅描述第一版。

旧 M36 (`36b0401`) 仍为 FAILED：21 个完整会话预测/46 答案，末会话另有2个实际响应，
qa2 在 HTTP 前因32446输入终止。22份维护结果中17 completed/5 incomplete，
43去重提交、6 current_boundary_source_required 拒绝。旧数据不补成新候选轨迹。
旧闭合成本为162生成/1748782 known tokens、140 encoder/18648 tokens，新增unknown0。
原全局账本固定闭合值49574请求/227101922 known/227378618 charged、2042879 embedding，
历史 generation unknown6；不重置或把后续实时账本差额误记成旧 M 成本。

第一版集成后29项受影响正常 SQLite/模拟 HTTP 检查通过；受影响文件 Ruff、严格类型检查
及 package/tools 依赖边界通过。检查记录在本地 ignored 验证产物中保存。
模拟调用不计真实模型样本，也不宣称完整仓库或远端 Full 通过。
第二版请求修复19项检查、合流后的共同投影及正常Host10项检查通过（包含重叠复查）；
三项新Reader检查与Source开发者12项既有检查另有闭合记录。六个受影响源码严格类型、
Ruff、依赖边界及旧八事项真实模板复算通过。没有把重复检查累加为新样本。
开发分支另合入`e41787a`：仅两处已知写入前遗忘拒绝返回effect=none，验证及异常路径不变。
开发者5项窄检查和Root合流后1项真实SQLite检查通过（重叠）；写入后回执丢失仍为unconfirmed，
裸旧rejected回执仍为unknown。该补丁未进入冻结`1cfb400`，不改写实验身份或历史结果。

## 下一项工作与仍未完成范围

原三链20输入及两段成本已核对，实际限制、原恢复control与失败均保留。先闭合四用户前缀预测，
再使用原评分入口统一评分；当前未运行Judge，没有方法优势结论。
工程错误与普通语义失败分别定位；unknown HTTP、未知写入/业务效果和 Store 故障停止相关路径，
不盲重试。新 benchmark 预先声明按题保存成功及已知只读缺答，缺答保留在全部机会分母。

四开发用户前8会话正在从各自空库形成，实际分母为32会话/73QA/72原生更新；
预测全部收集后统一评分，不用于跨版本排名。最终仍需同版五方法各277会话（合计1385）、
原 native32/12会话/4用户、drift/recovery、必要 M 消融与紧预算、最终冻结后的16保留用户、
LongMemEval、RawRAG/RollingSummary/A-MEM真实适配，以及 Host135case/192message 和新故事。
六项最终交付和方法选择均未完成，Product 仍为 NO_GO。工程可用、模型语义与科研优势分开判断。
