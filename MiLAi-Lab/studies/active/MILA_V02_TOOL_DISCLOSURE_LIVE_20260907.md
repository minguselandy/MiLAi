# MILA-V02-05：工具来源跟踪的真实公开接口验证

状态：`PUBLIC_TOOL_PROVENANCE_VERIFIED / FORMAL_E2E_NOT_ENTERED`。
本轮补充上一增量仅有替身的边界：独占真实PG/Runtime/MCP返回的数据进入当前Host适配器，
来源撤销后，四条工具路径均阻止旧上下文重发及派生文件读取，独立合法文件仍可用。

`tools/check_v02_tool_disclosure_live.py`通过公开接口建立一条合成Evidence、一个Proposal，
并以静态工程夹具走公开Review生成一个Claim。此治理仅发生在本轮专属测试实例，未开放给
模拟Agent的普通工具白名单；没有写共享Canonical，也没有直接写数据库表。

分别以全新的FileDisclosure取得Capture回执、Proposal单条、Proposal列表和精确Claim，
防止已有依赖掩盖某条路径的引用遗漏。真实Claim返回`memory-state-view-v0.1`及正确来源ID，
四条路径均登记相同合法来源，先通过当前资格核验，再经现有`write_file`产生派生文件。
公开撤销来源后，四条路径的`before_request`与派生文件读取均报`FILE_DISCLOSURE_DENIED`，
文件发现结果隐藏受控派生文件；普通独立文件仍可读取。

实际记录7次显式MCP调用和20次来源metadata GET，均有开始/结束及响应/资格观察；其中
12次GET观察到撤销。MCP内部SDK请求、初始化和后台投影另有开销，这两个计数不代表所有
物理请求。没有模型、Provider tokenize或付费依赖调用。本轮验证公开数据与Host适配器，
没有重新运行模型会话；上一增量的实际`_session`替身检查仍保留其独立归属。

运行根：`artifacts/v02-e2e-generality/tool-disclosure-live-20260907a/`，含计划、源码摘要、
7份公开调用/回执、20份资格观察、结果和清理。Product源码/pin未改，运行前后重新验证为
`56a0dab6df6dedd4540d3cc5a59fc1f9013505275e91cb7050b3d8eb56482e0c`；
检查器源码与运行前摘要一致。PG 2CPU/1GiB、进程CPU0/1，未重新测量或优化500多ms延迟。

启动前使用运行专属名称并拒绝已存在的容器/卷；两个新增负控验证本检查器不会在名称
占用时启动或停止既有服务。成功后API1234308、worker1234309、MCP1234427均已退出，
PG停止且非OOM，数据保留。共享vLLM和公开MCP未改。

Lab **372 passed，2.71s**；boundary、Ruff `src tests tools`、mypy `src/milai_lab`
（30源码文件）、build通过。Product源码未改，不将历史Runtime回归数量算作本轮执行。

T18/T19增加真实公开接口证据；未声明来源的自动识别、原生Host全工具路径、并发撤销竞态、
租户公平和模型效果仍未由本轮证明。完整D0–D3/P1/P2/P4与D4/D5未完成，新增模型额度仍0。
当前约532.5ms按用户要求可接受，后续继续闭环及剩余隔离/故障、Host成本工作。
Schema保持`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
