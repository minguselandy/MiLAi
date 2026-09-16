---
goal_id: MILA-V02-24
revision: R05_RETAINED_STATIC_RESEARCH_TESTBED
status: PROPOSED_TECHNICAL_SUBCONTRACT
gate_a: NOT_PASSED
model_allocation: 0
http_allocation: 0
memory_valid_denominator: 0
---

# R05：冷进程固定静态证据版本的研究测试床

本子合同接续 [v0.3 主 Goal](MILA_V0224_Gate_A至E最新执行与研究_GOAL_v0.3_20260913.md) §4
允许的长路径超限后测试床简化提案。用户已委托代理承担独立审查；代理不是人类审查者。
具体边界与反例见 [R05 合同草案](/cra/memory/mx_memory/evidence/v0224/20260913-a-zlib-feasibility-v1/simplified-testbed-contract-draft.json)。
本文及草案需独立技术审定；它们不授予模型、HTTP、设备或实际实例执行额度。

R04 A1 的九次 runtime 并集为 20.208416342 / 20.984938971 / 20.303233425 秒，均超过 18 秒。
原失败保留。固定 zlib 探针完整退出，解码 1.491189601 秒；未测完整事务收益，压缩路线不再实施或复测。
R05 明确减少静态存储新鲜性保证，不宣称另一项同保证优化。

## 替代的保证

每一个实际冷 worker 与 stage parent 各自为自己的 Batch 初始化一次固定静态 authority：
原 R04 scope 完整读取、外部摘要验证、全部 metadata/blob 校验与 mandatory fresh 首尾检查均成功后，
才能发布绑定 exact bytes/index、外部 pins、PID/thread 和 Batch 身份的只读句柄。
初始化与释放计入实际 worker/parent/阶段生命周期，不从耗时中扣除；无跨 Batch、进程、fork 或线程复用。

后续每次准入仍创建新的动态 scope。只对明确封存的 STATIC_TREE 和唯一 bundle_path 使用已验证的
不可变内容及索引；manifest.inputs 对该固定包路径的显式读取也使用该内容，不能报告成物理首尾读取。
若该包路径同时声明为 mandatory fresh 则拒绝分类冲突。当前 Note、World、工具结果及公开输入不进入此缓存。
receipt、全部其他源码/环境/公开输入/当前 artifact、57 历史账本、四个历史 SQL 根，以及授权、撤销、
stop、owner、CAS、operation、receipt、期限与独立业务效果均保留原来的逐次检查和物理关闭义务。
普通静态成员作为当前 artifact 使用时仍提升为物理读取；唯一固定包路径例外须明确报告。

明确失去的保证：初始化完成后，同一进程中的后续准入不再发现静态包路径的替换、删除或身份漂移，
不重复静态 metadata 构造和逐 blob 哈希；相关重复调用及资源异常不再等价。
使用的证据仍是初始化时经过完整验证的原字节。不得据此宣称静态存储持续新鲜或生产系统具备该保证。

## 新证书与后续研究的条件

新证书名称为 `GATE_A_CPU_RESEARCH_PASS_UNDER_R05_RETAINED_STATIC_AUTHORITY`，并同时标注
`LIVE_NOT_ADMITTED / MEMORY_NOT_ADMITTED`。它仅替代 v0.3 A1/A2 中静态包逐次新鲜性压力要求及
B 入口所接受的对应 CPU 研究执行有效性证书，不能填入 `GATE_A_PASS_UNDER_R03_R04`。
最终 A–E 结论必须明确适用于 R05 测试床；旧 A0、A1、压缩及准备失败均不改写。

开发后必须新冻相同四轮两动作形状的六位置校准，逐 S 九次并集≤18秒、严格 U 整个 worker≤60秒、
六位置 parent≤600秒。之后仍需完整 K3 的 16+80 reference、24 效果链、40 个独立冷进程和父 finish/gate，
链及归属父准入≤90秒、P3≤900秒（硬1800）、P4≤3600秒（硬7200），准备300秒/完整参考准备3600秒，
以及绑定当前源码的全工程终态。没有放宽原时限或借旧位置凑数。

R05 不改 B16/16、C24/24、D 的无旧 Note 自然能力/真实恢复/世界覆盖，或 E 的自然 Note、公开冷读、
相同信息对照、普通同调用 review、完整矩阵/分母与成本。所有比较臂采用同一静态初始化策略，
动态业务世界、记忆与权限仍分别新鲜验证。后续模型和 HTTP 每批仍须具体合同，不由本证书直接放行。
