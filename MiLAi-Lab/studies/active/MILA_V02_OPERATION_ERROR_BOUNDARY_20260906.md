# MILA-V02-05：错误回执不能凭文字提及证明写入被拒绝

2026-09-07（Asia/Shanghai）完成，文件名沿用20260906标识。本次修复Lab当前分层保存
适配器的结果归属问题；Product与公开接口未修改。当前Product pin仍为
`d6343d4b34c1f85ab40780cd12f4ac89fb5e34b3055b4d99edd8d1fb8084f337`。

## 问题与修复

`tools/v02_e2e_state.py:save_layers`原先在`json.dumps(receipt)`全文搜索四个已知拒绝码。
如果未知提交错误引用了`OPERATION_CONFLICT`，或回显payload包含`STALE_WORKING_STATE`，
它会把本应保留UNKNOWN的操作记为REJECTED。GET内容即使相等，也不能补足操作确认。
新增7个负控制全部复现该问题：修复前7失败，期望UNKNOWN而实际REJECTED。

修复仅读取明确的错误位置：顶层code，或者唯一text错误块开头的原因码。兼容当前公开
MCP实测包装`Error executing tool milai_working_state_update: `及裸ToolError文本。
嵌套payload、详情中的提及、码名子串、其他工具包装、冲突的多文本块都不证明拒绝。
格式/原因码不明确时继续UNKNOWN；没有新增GET、重试、写入或备用请求。

既有成功回执确认、版本比较、当前head观察和比较机会规则保持。没有从错误正文推导
新的权限，也没有改变Product CAS或事务。旧实验结果和旧候选文件未重写。

## 真实公开接口确认

执行前冻结独占Runtime/PG和三个独立任务绑定；MCP通过已有公开observer启动，各case
使用独立客户端。没有Product私有导入、直接数据库写入或模型会话。L1/L2文件保留完整
首尾和正文，其中错误码只是普通笔记文字。

| 场景 | 工具调用数 | 适配器操作结果 | 当前head | 比较机会 |
| --- | ---: | --- | --- | --- |
| 真实提交后丢失回执，错误详情提及拒绝码 | 3 | UNKNOWN | v1，内容匹配 | false |
| 真实提交后另一合法写入推进，再丢失原回执 | 4 | UNKNOWN | v2，内容不同 | false |
| 另一合法写入先获胜，候选使用过期版本提交 | 4 | REJECTED / STALE_WORKING_STATE | v1，获胜者内容保留 | false |

前两项在Lab传输包装层替换实际成功回执；真实成功回执单独保存在oracle记录，不提供给
适配器。第三项的拒绝来自真实公开MCP/PG，当前实际错误包装被保留并正确解析。
适配器每项只尝试一次候选写入；另外两次竞争/推进写入为预先声明的独立操作，不是重试。
这证明本范围的确认与head归属，不证明模型选择保存、冷恢复效果或阶段整体PASS。

## 计数与验证

合计11次显式公开MCP工具调用、3个observer进程。日志可见HTTP记录：readyz GET200为3，
MCP POST200为32、POST202为11、GET200为11、DELETE200为11；它们包含协议流量，
不能和工具调用相加。Runtime API日志没有逐请求访问记录，其物理请求数保持null，
不从11次工具调用猜测或填0。本次未测延迟/SLO。

模型生成和Provider tokenize均0；开发对话/工程劳动未计价，不宣称工作免费。
自有API/worker、3个MCP进程均确认ABSENT，PG确认停止，数据和失败证据保留；共享服务未动。

新增11项测试包含7个未知结果负控和4个合法错误格式正控。
`uv run pytest -q tests/unit/test_v02_e2e_state.py`为36通过（0.89s）；
`uv run pytest -q`为320通过（2.56s）。`uv run milai-lab-check-boundary`、
`uv run ruff check src tests tools`、`uv run mypy src/milai_lab`（30文件）及`uv build`通过。
Product源码未变，没有重跑或追认上一轮Product回归。本次不涉及schema/migration/部署；
格式无法识别时保留UNKNOWN可能减少可判定样本，但不会把未知写入强行归为失败。

原始计划、修改前源码摘要/失败记录、逐工具事件、oracle与适配器结果及清理检查位于
`artifacts/v02-e2e-generality/d1-operation-error-20260906a/`。
完整P1/P2/P4、D2真实Provider及D4/D5仍未完成，模型额度仍0；Schema保持
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
