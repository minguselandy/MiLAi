# v13.2 共享生成额度的限定工程验收

默认关闭的 `durable_shared_v1` 已合入，验收只覆盖持久计数和恢复拒绝；实际实验配置尚未启用，D4仍为NOT_ADMITTED。历史R5保留209源码676ad5dc，合入后的210源码b010a107不得冒作R5运行身份。完整身份、原回执/hash和限制见[验收清单](../data/manifests/v13-2-shared-admission-acceptance.json)。Source提交090901b已推送并精确核对；Root转入提交552e014。

同一public message以实际owner/bank/session/request ref/body SHA与冻结配置绑定计数。实际start/resume阶段显式传入；可信共享计数承担上限，Host checkpoint仅作下界交叉检查。计数修改用flock、临时文件/fsync、replace与目录fsync，在dispatch前保存reservation。缺失恢复file/key、损坏或不兼容状态、非法数值、receipt/count不符、身份变化及低于checkpoint/live下界均拒绝。未知请求占用原额度，不自动退款或重试；全局预算在wire前拒绝也可能保留已占用槽位。

Root核对Source15条原命令、前后完整源码/测试/配置map及209份原产物；最终33项新检查和17项相关默认检查通过。六方法默认AST与原default wire/receipt/capacity对照相同。Source四次非零命令全部保留：空工具oneOf[]导致首轮17PASS/15FAIL、错误M replay字节预期导致第二轮30PASS/2FAIL，以及ruff三处宽度/mypy两处Any返回。修正的是样例、预期和类型/格式，未放宽旧运行合同。

主树合入后再次执行50项相关检查，通过；ruff四文件、mypy三文件和package/tools两边界通过。五条Root命令均保持210源码、测试和配置map与Source最终版本相同。模型invoke、现有native callback和GroundedRecipe采用禁socket的MockTransport、局部SDK/SQLite与独立合成账本；Linux进程退出截断保留真实原日志。真实模型/embedding HTTP0，权威连续账本SHA26f46d5f不变。

Root发布辅助脚本的Python3.10 UTC import与将read_files整数误当列表两次错误也保存原脚本、错误记录及中间清单。修正审计器后写出验收；没有改运行实现或重跑已通过的测试。

脚本化summary调用不是B6+形成实现。flock在dispatch前释放，这项改动不构成HTTP串行锁或跨进程owner lease。结构校验及实际身份/下界不提供完整状态回滚的外部证明；本机fsync与os._exit检查不证明任意硬件掉电恢复。保存admission后、保存Host checkpoint前中断可能拒绝恢复，不能冒称完整W恢复已闭合。默认legacy包括其原缺失计数fallback仍保留。

共同reader/cache、闭合形成边界、B6摘要、Host写工具策略及[共同HTTP串行边界](V13_2_SERIAL_HTTP_AUDIT.md)仍待实施和验收。未运行完整测试套件或远端CI，没有模型收益、泛化或完整四臂预算结论，Product保持NO_GO。
