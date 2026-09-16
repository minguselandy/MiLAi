# V0222 E1 恢复阶段只读预审（未准入）

当前仅为用户委托 subagent `/root/batch_guard` 完成的实现可行性预审，
不是正式阶段 manifest、授权实例或模型成绩。P3/P4 尚未通过，E1 为 `NOT_TRIGGERED`。
配套要求见[后续路线第5节](V0222_后续执行与Memory再准入规划.md#5-e1真实错误恢复单独的未来合同)。

原 Session 的 `RECOVERY_ORACLE` 虽有五轮配置，但运行入口明确拒绝该 profile；
普通 Oracle 在首次版本冲突即停。P4 Provider 不接受外部 World 变化或澄清，
其独立效果 checker 又要求首投成功。因此不能仅改阶段名、cap 或取消旧 stop。

如果前置门通过，最小新接线应复用原 Session 的 dispatch/observe、ActionAdapter 和 World，
另建恢复 runner/Provider/事件感知审计，不修改旧冻结代码。只豁免事前指定的首次版本拒绝。
未知提交、用量、身份或其他漂移仍停发，不根据 World head 猜测失败后重试。

两类场景的可行五轮参考路径如下，正式合同还须冻结而不能事后解释：

| 轮次 | 版本变化、适用前提未变 | 版本与适用前提均变 |
| --- | --- | --- |
| 1 | 原版本写入触发真实 VERSION_CONFLICT | 同左 |
| 2 | read current 核验公开版本与适用条件 | 同左 |
| 3 | 模型自主提交新版本完整动作 | 模型提交 request_clarification |
| 4 | read records 回读 | read pending 回读 |
| 5 | finish | finish |

“至多三次后续生成”须明确为第2–4轮恢复行动，最后的交付 finish 单列；
不能声称总链只有三次后续生成。每链仍最多五次、16链理论最多80次，不增加机会。

在首个已校验模型动作返回后、派发前，通过 `World.publish()` 发布一次预定事件，
不改模型输出、不伪造拒绝；未触发故障为 `NOT_EXERCISED`。前提未变可重新发布同一 current，
改变版本与事件历史而不制造新业务事实。前提改变必须由各根预先选定的公开事实支持。

尚待正式设计解决：四根没有统一适用条件字段。每根事件和 rubric 须基于公开来源，
保证一次完整 current 回读足以判定，不注入正确动作或标准问题文本，不查看新池/gold。
澄清会写 pending、增加版本并产生真实 receipt/ledger；“首次拒绝无副作用”不能被误解为
“整条合法澄清链零副作用”。模糊或多解条件应保留分歧/UNKNOWN，不由审查意见冒充真值。
