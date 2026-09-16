# V0220 兼容修复：业务约束不变，生成语法与验收分离

日期：2026-09-11。用户要求：设计解决方案并修复问题。

结论：**双层合同修复已实现；8/8 wire Schema 通过 CPU 校验，真实生成尚未验证，V2 未恢复。**
历史未知用量仍为独立停发条件。本报告补充后续修复，不改写旧批与加固报告。

## 1. 解决方案与代码

[设计文档](../../docs/V0220_PROVIDER_WIRE_FIX_DESIGN.md)明确将两个合同分开：

1. **完整公共业务 Schema**：保持原字段、合法目标、类型、唯一性和其他规则；仍呈现给模型。
2. **生成语法 wire Schema**：只在已审阅的正向 Schema 位置移出后端不支持的 `uniqueItems`。
   每个变化都有 JSON pointer、原值、canonical/wire hash 和版本记录。

生成语法允许的集合更宽，不能宣称 grammar 等价或模型生成行为不变。
原始输出必须通过严格 JSON 与完整公共 Schema；通过后，原 Session 和 ActionAdapter 仍执行原校验。
**没有删除业务唯一性约束，没有自动去重、排序、修复、选择答案或过滤合法业务目标。**
解码约束的变化需要在未来各比较臂共同使用，不能把它引起的工程改善归因于 Memory。

| 新模块 | 职责 |
| --- | --- |
| [wire contract](../../tools/v0220_wire_contract.py) | 明确版本、保守编译、完整合同提示、原始输出校验；负向/未审阅运算符 fail-closed |
| [wire Provider](../../tools/v0220_wire_provider.py) | 可选入口；HTTP/usage 先保留，输出验收后才释放给 Host；无隐式重试 |
| [wire admission](../../tools/v0220_wire_admission.py) | 四根 full/finish 完整矩阵，原/wire 对、提示改动、请求选项、证据与容器/库状态绑定 |
| [全量兼容检查](../../tools/check_v0220_wire_compat.py) | 16 项原/新 CPU 参数校验；25 完整参考记录和语义反例校准 |
| [停发审计](../../tools/audit_v0220_wire_fix.py) | 新兼容门可通过，真实旧未知账仍阻止发送；零 HTTP |
| [40 项测试](../../tests/unit/test_v0220_wire_compat.py) | Schema 转换、JSON 等价性、负控、mock HTTP→Session→真实 SQLite、账本与无重试 |

旧 Provider、Session、World、V2 runner、加固模块、完整业务 Schema 及冻结原始证据未改。
未通过变更共享 vLLM 配置、依赖/镜像、GPU 权限或重启服务来取得通过。

## 2. 安装环境的验证结果

使用原四个已暴露 root、25 个合法目标，不打开新题：

| 范围 | 原始合同直接作为生成语法 | 新 wire 生成语法 |
| --- | --- | --- |
| 四根完整动作联合 Schema | 3 拒绝 uniqueItems，1 CPU PASS | 4/4 CPU PASS |
| 四根 finish-only Schema | 4/4 CPU PASS | 4/4 CPU PASS |

共 16 次实际安装代码的参数验证，全部引擎提交计数为 0。
使用既有已披露 CPU stub，验证到参数校验后即主动停止；没有 GPU 推理、实际输出或 usage 结算证据。
因此原后端直接接受 uniqueItems 的能力没有改变，新入口通过的是显式兼容语法。

完整记录校准：25 份已暴露参考记录均保持完整字段，解码→提交→公开回读一致；
25 次相同操作重放未增加业务效果，25 次陈旧版本新操作被拒绝，25 个身份注入反例被完整校验阻止。
4 个重复项反例全部被完整校验与原执行器拒绝；其中 2 个仍可由 wire 表达，直接证明后置完整校验不可省略；
另外 2 个同时触及仍保留在 wire 的其他限制，不能算独立唯一性约束证据。
这些是机械参考夹具，不评价旧业务争议，不是自然模型或 Memory 成绩。

新单测包含 121 种小数组枚举，检查原合同合法值不会因转换被排除；数值 1 与 1.0、
对象/嵌套数组按 JSON Schema 唯一性处理；true 与 1 仍为不同 JSON 值。
同名属性、default、enum、example 不被当成关键字删除；not/oneOf/if/$ref 等未审阅组合在发送前拒绝。
模拟 HTTP 的真实隔离 Session 完成两次业务写入、回读、finish；重复项在任何业务效果前被阻断，
其模拟已知 usage 保留。该测试不是一次真实模型请求。

## 3. 历史未知用量与当前停止边界

真实旧账本再次只读核对：请求 3 次，已结算 2 次 / 2,221 raw；未知 1 次 / 28,284 raw 预约。
**实际总 raw 仍为 null，未知预约没有释放、抹除或按 CPU 结果结算。**

完整新兼容准入的八种 Schema 已逐项通过接线审计；随后用真实旧账本调用新 Provider，
得到 `UNSETTLED_USAGE_NO_RETRY`，HTTP 调用列表为空，未产生新预约或生成。
兼容门与未知用量门保持独立：修复前者不自动解除后者。

原 V2 的 23 条未运行链、V3–V5 未触发、C=0、A0/Schema NO-GO 保持不变。
本轮新增真实模型请求 0、Judge 0，无业务/公网部署、保护池访问或共享服务变更。
新增提示字节由 Provider 逐请求记录并参与原 tokenize/上下文预约；未声称零额外开销，
未针对真实完整轨迹重新测量 token 容量，也未执行 generation 以外的在线 tokenize。

## 4. 冻结证据与检查

Git 外目录：`/cra/memory/mx_memory/evidence/v0220-wire-fix/`。

| 文件 | SHA256 |
| --- | --- |
| 20260911-v1/manifest.json | 5064dbb5139f134cfc304e92266d81efd7857b56b5f85a4917ea5112bf6c6561 |
| 20260911-v1/result.json | bde9f7e751fe4b716341984e1d6817c6d6c1aa65e33a739cd4b99b418b1ac196 |
| 20260911-audit-v2/result.json | dd7782d1d9696ca26529fe9ffc089aeb697de6ae8ea98d328f374ca2649b1c06 |

首次审计 v1 也通过，但其源文件随后只有行长格式修正；保留 v1 执行源码/结果，不回写旧 hash，
另以当前源码重新封存并运行 audit-v2 作为最终接线证据。早期 Ruff 格式问题修正，不涉及模型失败或挑题。

全仓库重新验证：**1545 passed / 1 optional Host SDK skip（50.56 秒）**；
边界检查、Ruff、Mypy（39 个源文件）、sdist/wheel 构建通过。新增 40 项测试均通过。

## 5. 下一步怎么使用

这是可选 Provider，不接管旧批。后续新批可通过 `WireSchemaAdmission` 验证新矩阵，
再将 `WireProvider` 传给既有 `Session.run()`；示意见设计文档。新批必须固定这次变换和新增提示，
不得只对某一比较臂启用，也不能用去掉完整校验的裸 wire Schema 执行业务。

实际恢复仍需两件事：

1. 明确历史未知用量的处理依据，或明确授权保留未知账的独立诊断；当前代码不会自动豁免。
2. 单独冻结并运行有界真实生成兼容验证，核验实际服务配置、输出、usage 和上下文容量。
   CPU PASS 不证明共享容器 GPU 健康或完整服务端解码，也不直接启动 V2。

本轮交付标签：`WIRE_COMPATIBILITY_REPAIR_IMPLEMENTED_CPU_VERIFIED / LIVE_NOT_VERIFIED / V2_NOT_RESUMED`。
修复仅针对 Provider 兼容路径，不能称动作有效性门、自然任务门或 Memory 机制已通过。
