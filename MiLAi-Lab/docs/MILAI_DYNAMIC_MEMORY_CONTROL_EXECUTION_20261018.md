# 动态记忆控制 v2 执行记录

2026-10-18，完整目标 active。依据 `MILAI_DYNAMIC_MEMORY_CONTROL_DEVELOPMENT_EXPERIMENT_PLAN_20261018_v2.md`。

当前切片 D1：共享有限动作循环、规则/固定/Laya/生成式策略、正常 Host 的证据交付接线。
USE_VIEW 只打开原 Store 的视图；REFRESH_VIEW 才调用原解释生成器。
本地 Laya 推理从评测脚本提取至 provider；旧脚本继续调用同一实现。基础权重明确作为零样本诊断。

配置：`configs/dynamic-memory-control-d1-v1.json`。沿用原连续账本与现有7860生成/7861嵌入服务。
旧7862端口当前不可达，已在本配置改为实测可用的7860；没有启动服务或恢复旧任务。
运行环境沿用 `artifacts/jev-reader/cuda-env`，以 site.addsitedir 加载原 http-env 的 Host 依赖；未升级依赖。

验证：129 项 Host/记忆集成测试通过；查询视图/旧训练工具局部组 27 passed、3 skipped，
在原 Laya 环境补跑训练/度量组 9 passed（覆盖那 3 项）；8 个触达源码文件 mypy、Ruff、
package/tools 边界通过。各组有重叠，不求和；未声明全仓或远端 CI。

首次真实运行 `artifacts/dynamic-memory-control/d1-laya-v2`（代码61124918）退出，
`save-1` 已完成真实语义提交，但回答阶段失败：操作日志缺原 Trace 的 event 字段。
Laya 前向 0；生成 10,528 tokens、嵌入162 tokens，新增 unknown0。原失败与已保存状态保留。
2a4f83d2 修复原日志合同并增加真实 Trace 回归（6 passed）；新身份 `d1-laya-v3` 再次退出失败：原 HTTP owner 拒绝请求外的本地模型计算记账。
本次生成13,032 tokens、嵌入218 tokens，新增HTTP unknown0；本地加载尝试的时间未留存，
不能记成0或伪造精确费用。没有完成可用的Laya前向回执。
原账本新增窄的 local_compute 串行入口，仍不允许其中预留假HTTP请求；8项相关测试通过。
下一身份 `d1-laya-v4` 使用正常Host的来源导入加真实查询，先验证读取。
`d1-laya-v1` 只有未执行的 prepare，未产生模型调用。
当前仍为单槽，每请求一次显式 Source 枚举；不声称增量发现或动态策略收益。
不执行 SHA/checksum/内容指纹校验，不改历史实验，不推送/合并，不使用子代理。

下一项：首条真实闭环后，六条独立连续历史从空库运行 C0/C1/C2-base，再加入 C3。
随后完成新家族操作标签与 CE/自身轨迹、两槽和变化复用、匹配机制对照、新保留家族及全部声明种子。
D5 可选维护与表示复用按计划的结果条件决定，不用旧选材权重冒充操作训练。
功能可用性、任务/状态结果、完整成本和论文主张分别判断；当前目标尚未完成。
