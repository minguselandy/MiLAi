# V02-06：原生 Codex 协议起点与实际兼容缺口

状态：`U0_PARTIAL_NATIVE_OFFLINE_ROUNDTRIP_VERIFIED`。新Goal已获执行指示；本轮没有发出
真实模型生成、付费或公网记忆写入。旧V02-05及D5任务编译材料保留，不作为新主线前置。
原产品规划SHA仍为`9660f952ea54539c5cd1dd73fdab7c5fdcf07190f1d37e8b9357332dcf0c88e6`。

## 实际运行身份与隔离

- 原生`codex-cli 0.153.0`，二进制SHA
  `fce635028842bfe9257140e8b7d53162732945e2f356fc35225be0702b4974be`。
- 客户端容器镜像`milai-lab-readable:v0204`，实际ID
  `sha256:822880bdaaa648ae9c1fa3c9bc20abfc88c7335030104b16038e46514b3362ad`。
- 容器`--network none`、只读根、2CPU/2GiB，仅挂载自己的空会话目录、工作区、Codex二进制
  和Unix socket连接。薄relay将该socket暴露为容器内loopback端口，不提供共享网络访问。
- 不挂载真实用户配置、认证、旧rollout、评价资料或Runtime密钥。没有MCP连接或记忆预取，
  这一轮只验证客户端/Provider协议。固定响应触发真实`exec_command`执行`pwd`。

入口：`tools/check_v02_native_protocol.py`和`tools/v02_native_bridge.py`。
原生客户端保留文件/命令能力；显式关闭多Agent、Goal及Web工具，避免额外执行路线。
使用独立Provider配置、`requires_openai_auth=false`、请求/流重试0、关闭WebSocket。
参考[官方配置文档](https://learn.chatgpt.com/docs/config-file/config-reference)，但以本机
`--strict-config`实际接受情况为准。首次尝试证明当前二进制不接受文档中的
`model_supports_reasoning_summaries`字段，已删除该配置项，未更换客户端。

## 三个零模型客户端记录

目录前缀：`artifacts/v02-mcp-usability/native-protocol-20260908`。

| 目录 | 实际结果 | 范围 |
|---|---|---|
| a | 配置校验退出1，Provider请求0 | 原始错误保留 |
| b | 捕获1个真实Responses请求，固定HTTP400后退出1 | 证明实际请求形状，不是模型兼容通过 |
| c | 2个固定SSE响应，客户端实际执行工具，退出0 | 相同call_id和`/workspace`工具结果进入第二个实际请求 |

实际工具定义为函数Schema；c包含exec_command/write_stdin/request_user_input/view_image。
这不是模型选择，也不是MCP保存/恢复。没有把初始prompt导出代替第二次请求：原始请求
JSON与摘要、固定SSE及客户端JSONL分别保存。模拟usage不可计入真实模型账本。

## 真实本地Provider发现

只读`/v1/models`与OpenAPI确认loopback服务及模型`Qwen3.6-35B-A3B-FP8`、65536上下文。
当前共享vLLM镜像ID为
`sha256:e0cfcfcb9b86e2c2d0d52a93689773f20f380cb8e050a24ce550c44f6f55c5eb`。

关键发现：实际启动参数有`--reasoning-parser qwen3`，没有`--enable-auto-tool-choice`
及`--tool-call-parser`。两个完整请求转换后调用公开chat render都返回400，明确说明未开启
自动工具解析。已读部署源码：Responses和Chat都通过同一ParserManager配置；不能凭
Responses路由存在就认为原生函数往返成立。共享服务未重启或改参数。

同样的完整消息/工具经公共`/tokenize`成功计数，首次5713、含真实工具结果的第二次5798；
耗时约0.238/0.023秒。计数包含指令、完整历史及工具Schema，未丢弃正文或字段。
这是两次真实tokenize、两次失败render，生成仍为0；尚无真实usage可确认生成侧计数一致。

曾尝试在共享容器中只导入部署的Responses转换函数，45秒超时。随后核对无遗留helper进程，
未调用生成。失败helper及记录保存在c目录，已从活动tools删除，不把整套vLLM Python导入
放入每次请求关键路径。当前薄转换仅服务文本/函数工具计数，不改变发往Responses的提示
或工具结果；不支持的媒体、加密reasoning和有服务端前序状态的请求明确不进入此合同。

## 预算核心与未完成部分

`v02_responses_budget.py`复用既有持久预约/结算账本和单在途锁，先按同部署模板tokenize，
再限制原生请求中缺失的max_output_tokens。保存客户端原请求和实际转发请求；两者只差
声明的输出上限。没有真实发送授权时不调用tokenize/生成；未知usage保留预约，之后停止。
缓存input作为input子集记录，不能再次相加。生成usage与计数不符或输出超预约都停止。

11项新单元回归验证发送前预约、完整转发、超额/未授权拒绝、未知/越界停止、并行工具ID
与结果保真，以及socket半关闭后的响应。该核心还没有接入原生客户端转发服务；绝对会话
deadline、真实模型usage及MCP结果关联仍需接通验收，不能记M13整体通过。

下一步只解决观察到的工具协议缺口：优先验证是否能在外部以最薄格式解码将模型实际输出的
工具调用恢复为Responses函数事件；保留原始输出和调用参数，不补模型决定或MCP结果。
若不可可靠实现，保留兼容失败；不自动改共享服务、启动付费模型或扩大探针额度。
无模型控制完整后再登记Goal建议的两次本地兼容探针，不能把本轮固定fixture算成这两次。

## 验证与收尾

```bash
uv run python tools/check_v02_native_protocol.py --root artifacts/v02-mcp-usability/native-protocol-20260908c --roundtrip
uv run pytest -q tests/unit/test_v02_responses_budget.py
uv run milai-lab-check-boundary
uv run pytest -q
uv run ruff check src tests tools
uv run mypy src/milai_lab
uv build
```

Lab全量543 passed（6.80秒）；边界、Ruff、mypy30文件、build通过。顺手修复旧任务编译测试
暂停时遗留的一处超长行，仅格式变化，没有重启旧任务或改其条件。Product代码未修改，
因此不重复其全量测试。三个客户端容器均已退出/删除，relay与本地socket观察器随之结束；
共享模型、公网MCP、数据库和其他用户服务保持。无新Product-backed记忆效果运行。

M01–M14仍需逐项取得所要求的工程或真实行为证据；当前只补U0、M03/M12/M13的局部前置。
U1/U2/U3/U4/U5均未由本轮工具fixture自动通过。Schema保持0.1.x EXPERIMENTAL /
Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE。
