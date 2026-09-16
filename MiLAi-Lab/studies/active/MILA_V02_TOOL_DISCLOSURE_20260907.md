# MILA-V02-05：补齐工具结果的来源跟踪

状态：`HOST_PROTOCOL_PROVENANCE_ENGINEERING_VERIFIED / FORMAL_E2E_NOT_ENTERED`。
本轮修复受控JSON-action Host的实际遗漏：精确Claim读取返回
`memory-state-view-v0.1.evidence_refs`，但此前FileDisclosure仅处理检索Context及Working State。
来源随后撤销时，精确Claim正文仍可能随历史进入下一次模型请求，派生文件也缺少该来源依赖。

## 修改与回归证据

`tools/v02_e2e_state.py`识别精确State视图的顶层`evidence_refs`；
`tools/run_v02_local_vllm.py`把实际调用工具名传给来源跟踪。对无schema标签的公开回执，
只读取以下明确的协议位置：Evidence capture的`evidence_id`、Proposal get/list的
`supporting_evidence_refs`和`contradicting_evidence_refs`。这些引用只用于披露资格，
不将Proposal或反证升级为事实；不扫描正文、patch或描述中的UUID和伪引用。
MCP错误及删除状态元数据不被当作取得新的正文来源。

取得结果时先检查当前来源资格，合法引用加入既有Context依赖；派生文件继承这些依赖。
每次后续请求前复查，撤销、范围丢失或metadata不可用时停止发送。正常来源继续可用。
复用现有metadata接口与deadline路径，没有新增Reader、语义审查、公开工具或Product实体。
增加的资格查询属于真实Host成本，不能假设免费；本轮未测量新增实际网络耗时。

先加实际`_session`路径的负控，修复前**1失败**：来源已撤销，Host仍COMPLETED并再次调用
Provider替身。修复后测试覆盖四种情况：合法来源正常发送第二次请求；撤销、项目范围丢失、
metadata失败均在第二次请求前终止，第二次输入中不出现受控canary。
这里的Provider、公开工具调用及metadata均为网络外替身；是实际Host代码路径验证，
不是新模型运行或新增真实PG/Canonical Claim验收。

另外7项合同控制验证显式引用跟踪、派生文件继承，以及正文伪引用、MCP错误和状态元数据
不产生错误依赖。全Lab **370 passed，2.84s**；boundary、Ruff `src tests tools`、
mypy `src/milai_lab`（30源码文件）、build通过。首次修复后的相邻检查49通过、1.08s；
随后补充合法及两种额外拒绝控制，计入最终370项。

## 归属与未完成范围

证据根：`artifacts/v02-e2e-generality/tool-disclosure-20260907a/`。
Product源码不变，pin重新核验为
`56a0dab6df6dedd4540d3cc5a59fc1f9013505275e91cb7050b3d8eb56482e0c`。
没有启动服务、模型或Provider tokenize，没有写Canonical；旧实验源码归属不改。
本次是Lab受控Host修复，不外推原生Codex所有工具路径或未声明来源的自动识别。
已经发给模型的内容不能通过后续撤销收回，本修复控制的是后续发送与派生文件披露。

T18/T19取得该Host路径的补充证据，完整D0–D3/P1/P2/P4及D4/D5仍未完成。
当前约532.5ms继续按用户要求视为可接受，不恢复300ms优化。新增模型额度仍0；
下一步继续剩余真实隔离/故障与Host成本条件。Schema保持NO-GO。
