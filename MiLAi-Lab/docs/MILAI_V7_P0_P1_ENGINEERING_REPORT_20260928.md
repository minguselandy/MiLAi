# v7 P0/P1 工程结果

P0 只读复核完成，P1 已在现有普通记忆路径中接通 JSON/native 的共同材料投影、容量和交付审计。
源码 A 为 `37d48577bdff582f74faf2f5e663b359885350ec`，远端分支已核对一致，见[draft PR #71](https://github.com/minguselandy/MiLAi/pull/71)。
这份结果只证明工程接线及局部兼容性；真实 native 协议比较当前为 `BLOCKED_ENVIRONMENT`。
尚未产生 v7 实验调用，效果以之后冻结的 E1 结果为准，Product 仍 NO-GO。

## P0 实际能力与旧失败

详见[能力清单](../data/diagnostics/development-experiment-v7-p0/protocol_capabilities.json)和
[四类旧失败链](../data/diagnostics/development-experiment-v7-p0/failure_chain.json)。
Root 阅读原计划 1055 行及架构复盘 487 行，hash 与计划引用一致，原设计状态和字节保留。
实际 Host 为 Qwen3.6-35B-A3B-FP8、vLLM 0.27.1、65536 容量；temperature=0、max_tokens=4096、
thinking=false。部署 config/tokenizer/template 四项资产与本地计数资产 hash 全部一致。
权重完整 revision 未独立取得；不以模型名冒充全权重校验。

实际进程没有 auto-tool-choice 或 tool parser，已安装的 ParserManager 与 serving 分支要求两者才
输出自动解析的原生工具调用。模型模板支持 tools，已安装 `qwen3_coder` parser，均不等于服务已启用。
该要求也见[vLLM 0.27.1 工具调用说明](https://docs.vllm.ai/en/v0.27.1/features/tool_calling/)和
[Qwen 官方模型卡](https://huggingface.co/Qwen/Qwen3.6-35B-A3B-FP8)。未发送 native 生成探测，
不声称实际观察到 HTTP400；没有重启服务、改 parser/template、下载或部署。

旧 H/I 的首断点分别为：明确保存后零 CREATE；完整业务 key 被改写；明确实时查询被 memory search
取代；formation 失败使预设部分副作用未激活。输入、provider ID、工具参数／结果、Store 与后续响应
从原 trace 核实。旧结果和 I3 的实际世界缺席分支评分修正保持，不能说部分失败能力已通过。
主要竞争解释仍包括协议表达负担、Host 语义／动作选择、compact 工作视图和字符串引用接口；
这些旧轨迹不能单独确定因果。

## 最小实现及真实边界

- 复用 RequestContext/Renderer，先形成同一合法材料与来源投影，再做 JSON 或 native 历史／工具编码。
  保留原 graph/checkpoint/tool JSON；JSON 既有协议文字和默认行为不变。
- native 的实际 tools 与部署模板参与最终容量检查，之后记录实际 delivery；不再绕过记忆视图。
  最终自然文本承担与 JSON 解码 `answer` 同样的内容、格式、语言和长度义务。
- 显式 `protocol_calibration_v7` profile 仅开放本轮 B0、严格工具、current_request/compact_v6、
  non-thinking、无 correction/Attention 的范围；旧 recipe 检查继续存在。
  不支持的 C/M1/ODR/旧 projection 或强制工具／response_format 组合明确拒绝。
- native 校验调用形状、工具名、对象参数、截断／finish reason、缺失或重复及历史复用的 call ID。
  同响应叙述标为 proposal，不能当执行事实；实际工具后仍需后续终答。
- 两 E1 配方共用同步 FoundationScope(max_concurrency=1) 与真实 ToolNode executor.map。
  依赖前一结果的 ID 必须来自实际回执；本配方不承诺异步 gather 串行。

改动为五个源码文件、三个已有测试文件和两个 E1 配方；无新 runtime、平台、持久状态层或依赖。
Root 独立核对 J/N 仅差 `host.tool_mode` 与 recipe 名称，J 相比原 v6 compact 仅新增 profile 与名称。
源码不含 E1 样本 ID、对象名称或答案字面量。

## 必要检查

精确命令、环境、日志 hash、覆盖与限度见[P1 检查清单](../data/manifests/development-experiment-v7-p1-checks-20260928.json)。

131 个历史实际 JSON 请求分别在 full/compact 回放；full 与冻结原请求及 S1 相等，compact 与冻结
S2 编码／tokens 相等。86 个操作审计、图／回执元数据和只读 checkpoint hash 不变。
原 trace 保存的是有序解析请求；检查比较锁定 HTTPX 编码与实际 MockTransport 字节，未宣称原始 socket 抓包。
这是编码级回归，非新的真实实验；不把历史 6870 token 差额重复记作 v7 实验节省。

56 个去重窄测通过（Core 20、Foundation 36；无 skip）。局部检查覆盖无工具、单／多工具、工具拒绝、调用后回答、同 ID 更新、删除后读取、owner 隔离、
部分成功、坏参数／未知工具／截断／重复 ID、实际同步调度，以及真实 tokenizer 的 tools 容量。
旧 query/Attention/C 邻接目标保持。最终目标 Ruff、Foundation Mypy、Core Mypy、验证矩阵、
package/tools 边界及 diff 检查通过；两个配方零模型 prepare 通过。

初次测试 harness 对既有错误文本的解析有两项失败，已局部修正并复核；初次 lint/type 问题修正后
通过，原日志保留。既有 LangGraph/LangChain 弃用提示不在本次升级范围。
未运行全量 benchmark、参数扫描或不相关测试，未因发布重做已通过检查，未构建或改依赖。
P0/P1 新 generation、embedding、共享 Postgres 调用均 0；本地工具与模拟 provider 属工程检查。

## E1 进入条件

源码 A 已发布；[E1 协议](MILAI_V7_E1_PROTOCOL_20260928.md)及输入将单独提交 B。
随后 Root 在准确已发布 SHA prepare/freeze：J 为 12 条可运行微轨迹／26 消息，N 同规模保留未运行。
评分必须沿实际 HTTP → 工具／数据库 → 持久化 → 后续交付 → 答案，不能由正常退出或 CREATE 提案
代替验收。原生环境阻断不阻止完成安全且有价值的 J 基线，但无法得出 J/N 协议优劣结论。
E2–E6 和第二模型仍在当前 slice 之外，未被自动启动。
