# P7 R2：局部容量失败不终止整个 arc

R1已在 `69c1a2ba9fecf3c90a1f8427f0dafe300985fe44` 发布并核对remote。B1与A5均因未形成记忆而在同一MERIT消息中重复空搜索，耗尽原12生成额度；runner外层停止遮蔽了后续任务。R1的partial结果及104生成费用保持不变。

本轮只修评估覆盖，不修Formation或authority。给原 `run_exposed_merit_arc` 增加默认false的 `continue_on_local_capacity`，新独立R2 config设为true，两臂同样启用。仅捕获本episode公开消息中的精确容量错误；保存失败消息索引和已完成/尝试/后续未尝试消息，继承实际world、Store与checkpoint，然后进入下一个原episode。服务/Store/instrumentation等错误仍向外中止。

保持原native公式 `not pre_satisfied and checker(after_world)`，原checker、工具、世界、原分母与顺序不变。Host容量失败单列，不能硬置native false，也不能把世界任务达成冒充Host完整结束。一个episode失败后其剩余未尝试公开消息列为skipped，不借后续任务补写成功；不重置同一公开消息额度、不提高max_calls、不回滚已完成业务。

先用一个必要离线反例覆盖：容量失败后下一episode运行；cap前已成功的业务仍由原checker如实计分；服务错误仍停止。新源锁与一次必要构建完成后，只跑原arc0的B1、A5两条新完整轨迹，独立空namespace和新输出。原十二例runner与方法没有语义修改，不为接线重复该批模型调用。

新config为 `configs/milai-ser-v22-r2.json`，新锁为 `data/locks/milai-ser-v22-p7r2.lock.json`。复用v22验证类型与函数，独立source mapping/config/prepared/协议SHA足以区分R1和R2；旧源码及锁从R1检查点复现。方法recipe/transport仍v21，authority、SER算法、Host/embedding、vLLM服务设置与账本均不变。

Root在运行前冻结两臂输入和失败策略，串行调用；起点306生成/274357tokens/3689embeddingtokens/75exact reads。native/dependent、Host完成、消息覆盖、动作参数、memory形成/检索、实际Provider送达与成本分别报告。若继续失败，保留并定位第一断点，不替换数据或宣称项目完成。

之后再独立检验无证据请求的authority开销与d11漏搜差异。该优化不能同时混入本轮；P8继续pending。Formation、Reconciliation以及P9–P12保持原长程授权。
