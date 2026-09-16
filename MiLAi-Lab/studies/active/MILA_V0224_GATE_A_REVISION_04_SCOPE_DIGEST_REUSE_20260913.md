---
goal_id: MILA-V02-24
revision: R04_SCOPE_VERIFIED_DIGEST_REUSE
status: DEVELOPMENT_DESIGN_NOT_EXECUTION_APPROVAL
gate_a: NOT_PASSED
model_allocation: 0
http_allocation: 0
memory_valid_denominator: 0
---

# R04：同一准入区间内复用已经验证的整包摘要

本修订继续执行 [A–E 主目标](MILA_V0224_Gate_A至E执行有效性与持久记忆研究_总GOAL_20260913.md)。
它保留 R03 静态证据包的权限模型，唯一拟议性能差异是删除原解析器末尾一次重复整包哈希。
用户已委托代理代替人工审查；代理审查不是人类审查。本文不批准真实实例或扩展网络范围。

## 依据与候选选择

R03 完整运行时校准的六个参考均完整完成，语义、效果和 SQL 不变性独立审计有效。
三 S 的七次完整 `Session.validate_runtime` 并集为 18.483173292、18.448296345、
18.298297905 秒，逐项超过 18 秒。该实例停止，不能补跑、修改或进入 K3。
独立报告为 `20260913-a-runtime-union-v1/independent-runtime-union-calibration-review.json`，
SHA `b453e5f2a913c1c621262c776dcd83fd305c63e0b4b68f8b8c0f8c9843710765`。

随后的一进程、同一已验证 buffer 的六次 API 分段诊断已独立审计有效。
固定 U/S/S/U/U/S 的配对耗时比中位数为 0.996397314781101；这仅认证 API 观测资格。
S 元数据前段约 63–70 ms，blob 布局和哈希循环约 398 ms，尾段约 395 ms，
其中嵌套的整包哈希约 392–393 ms，尾段其余约 3.2–3.4 ms。
独立报告 `20260913-a-parse-split-v1/independent-parse-split-result-review.json`，
SHA `4a910448b17e1c430a5c8c56ae579cb5c4ff29b40ffd0f05ff56dc62ecba0c9a`。
嵌套时间不相加，不将 API 时间乘以调用次数预测 Session 收益。

据此本轮只选同 scope 的已验证摘要复用作为开发候选，不实施跨 scope 元数据缓存。
尚无候选性能成绩。

## 精确差异及保留的保证

原 `AdmissionReadScope._entry` 调用 `_regular_bytes` 实际读取并计算整包 SHA256，
只有实算摘要等于外部 expected 后才赋予 `entry.data`。同一成功 entry 的 `data` 是
不可变 `bytes`。原解析器随后对该同一对象再次整包哈希，作为 `BundleIndex.bundle_sha256`。

新 scope 的词法私有解析入口只从原物理 `_entry` 获取数据及已验证 expected；
不接受调用者提供的裸 raw/digest/entry/token，不引入公开跳过哈希的解析 API。
入口与返回处核对 active/entered/owner、当前 registry entry、原 bytes 身份和外部 expected。
不能将 closed、poisoned、foreign owner、替换 entry/raw 或冲突 expected 当作验证结果。
不得额外重复调用 `_entry` 改写 repeat-reference 计数或原业务校验顺序。

只替换原 return 中最后整包 SHA256 表达式；以下工作仍实际执行：

- 每个 scope 的原始首次读取、路径身份检查及整包哈希；
- 完整 strict JSON、canonical header、路径、布局、环境和 immutable index 构造；
- 每个 unique blob 的全部实际 SHA256；
- 原始收口时再次读取、路径身份检查及整包哈希；
- 当前源码、四个公开输入、57 历史账本、四个历史 SQL 根、当前授权、stop、owner、
  CAS、operation/receipt、当前账本和收口后的期限检查，保持原顺序。

无跨 scope、跨进程或 admission PASS 缓存；不保留供未来 scope 使用的旧 payload。
Python 私有字段不是针对任意恶意同进程 Python 代码的密码学隔离；执行源码仍由外部 pins
固定，禁止未冻结或未明确授权的运行期 patch。已审定并绑定源码的
`installed_transaction_fix` 事务首因修复和 S 组新 Session 实例的观测 wrapper 继续保留；
它们不是本轮新增性能差异。原公开 `parse_bundle` 及所有已封存实现保持原样。

保证差异必须显式报告：解析器末尾那一次重复整包哈希不再运行，其独立调用/资源异常也不会
原样发生。不能宣称所有资源异常或调用计数完全等价。内容、授权和首尾新鲜性保证按上述保留。

## 验证及后续门

先用一般性合成反例验证原解析语句顺序、完整 index/raw 身份、首因与关闭失败保留，
并准确计数只删除一次重复整包哈希，首次、关闭及每 blob 哈希全部保留。
覆盖未进入/已关闭/poisoned/foreign owner、registry/raw 替换、expected 冲突、
首次/关闭内容或路径漂移、header/blob 损坏与动态 stop/owner/SQL 拒绝。
不得以案例 ID、固定 payload 或门槛数值决定是否走优化分支。

通过源码交叉独审后，新 Batch/fixture/父子流程与完整执行闭包须重新冻结；
新证据包、独立批准和所有新夹具共用原 300 秒准备预算。旧实例与源码不修改。
具体路径、顺序、输入、审查文件和进程命令由后续实际合同固定，未固定前不执行。

候选必须重新取得严格 U/完整运行时 S 的观测资格和逐项 18/60 秒证据。
历史 R03 基线只能作为历史参照，不拼接成候选成绩，不把微观差额当作端到端收益。
之后仍须完成 K3 的 16+80 参考、24 效果链、实际 16+24 冷进程、父收口/门检查、
原 90 秒链余量与阶段余量，以及绑定当前执行 revision 的完整工程终态。
B–E 的条件、分母、费用与公开 Product 边界不因本修订改变。
