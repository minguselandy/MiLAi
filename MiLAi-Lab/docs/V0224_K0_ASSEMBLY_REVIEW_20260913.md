# V0224 K0 汇编与实际 scope inventory 代理审查

审查者：Codex subagent `/root/gate_review`，依用户授权替代人工审查；不是真人认证。此次只读源码与既有 draft，未改封存源码、启动 fixture 或计时实验。审读时七份 `k1-*-inventory.json` 与 `contract-for-review.json` 尚不存在，所以以下是代码审查和最终冻结清单，不是实际制品验收结果。

| 源码 | 审读 SHA256 |
| --- | --- |
| `tools/assemble_v0223_k0.py` | `b5d990704c4645dbf17c132070c1b495dc9e48e917bc29d2639c74b3bd081546` |
| `tools/inventory_v0223_fixture.py` | `c25be2537328ae2e3748ae9cc2238b6c666f52d5cb6c440e5b124469d54361ec` |

## 已具备的合理边界

Inventory 在 guard 启用后构造新 OfflineBatch，实际执行 constructor 和一个 PREP operation。close wrapper 在原方法清除 entries 前仅取 metadata，原 close 仍执行、异常仍传播，最终要求恰好两个完整关闭 scope。它没有替换 reader/validator，也没有给出计时成绩。动态六表在当前 PREP 事务内按固定顺序读取，属于实测快照；比原 lineage+manifest 合并清单更接近实际准入输入。

Assembler 固定六对照位置加一个前缀位置，核对 root/binding、清单每文件当前 hash 及跨引用冲突，核对未启动/40 PENDING/单 binding meta/engineering artifact 名称，比较六校准位置的 scope stats，并保持输出 `K0_REVIEW_REQUIRED_NOT_TIMING_AUTHORIZED`。因此可用于生成审查草稿，不应直接改一个 status 字符串便放行。

## 最终冻结前必须补齐或明确裁定

| 项目 | 当前代码证据与限制 | 需要的最终审查证据 |
| --- | --- | --- |
| scope 清单真实性 | inventory 强制两 scope 完整关闭；assembler 只比较清单数据，不独立要求两条和每条关闭状态 | 独立核验七份报告、运行 terminal/hash；重算两条 status、文件数、bytes、JSON量，不能信标题字符串 |
| 同负担 U/S | assembler 仅比较 stats/文件数/status，没有比较逐路径角色与规范化内容；相等总数不等于同 bytes/同用途 | 六位置逐文件角色/内容比较，只有 root、episode/scope ID、时间等明确机械字段可映射；列 bytes 差异与原因。冻结公共源/World初态/hash/模型可见值相同 |
| 动态初态 | assembler 检查 episodes 的数量/PENDING，未检查 ID/ordinal/stage/cap/pid/deadline，未比较 artifact 正文/dependencies 或 accounting_state | 将每个 SQL episode 对齐冻结 plan、完整六表做机械映射等价；当前无新请求/预约、历史57账与旧未知仍承接；旧 STOP 不是新初态，需依据旧 initialize 源码和停止前历史解释 |
| 五/55 scope 负担 | constructor+一次 PREP 的两个 scope 不是完整首 P4 五 scope，更不是55前缀的逐边界动态变化 | 基于实际 helper/control flow 映射 constructor、setup、spec、Session初始/首loop；区分静态覆盖和 runtime增量。55前缀中P3生成的参考文件/动态变化不能由初始两scope冒充已观测 |
| 负控冻结 |八组/34节点计划标未执行并暴露缺项；“候选冻结后补测”本身不定义缺失测试注入时刻 | 对每个缺项冻结受控时钟/修改边界/拒绝类别/无副作用判据；K1前无需声称测试已通过，K2/K3前必须兑现相关覆盖。精确首因尚未知时标未证明，不预填代码 |
| 计时边界/重复上限 | draft 有6顺序、300/60/3600和1.10；仅有数值不足以定义生命周期归属 | 独立审读 worker/helper/parent 当前封存hash，绑定spawn→exit、Session含收口、报告及未归因成本、U/S相同计数负担、首失败STOP及仅一次55前缀触发 |
| 全阶段合同字段 | 当前 draft 是K1准备草案；原K0要求K2每侧3600、K3seal300/prepare3600、至多一个候选等 | 在最终合同显式引用完整V0223合同hash或列全部限制，K2/K3另在候选冻结后激活；历史 engineering 仅负担，不得作当前工程认证 |
| 输入证据封存 | draft `source_inventory` 有hash；assembler只直接校验scope files和负控文件，未递归核验所有草案引用，也未在同一 read scope 关闭时复核全部 | 最终独立封存前核验草案引用、源码依赖/执行副本、packages、inventory执行源码hash、所有授权与输入hash；对运行期间漂移保留原新鲜检查，不声称持续不可变 |

Assembler 第83行将 `missing_before_freeze` 无条件压缩成一项“独立审查/最终封存”。这只能理解为把所有详细缺项交给独立审查，不能解释为其余项目已由 assembler 证明。建议最终审查记录保留本表逐项裁定；不必为了改描述重封正在生成的 fixture，但最终新合同必须诚实保留所有未完成项。

以上大多可通过对已准备制品、现有源码与冻结规则的离线核对完成，无需等待真人。当前没有证据表明应中止正在执行的隔离 fixture 准备；但在这些内容完成前，不签 `K0_FROZEN`，不启动 K1。此次未运行工程测试，因为没有代码变更；不能借此报告升级任何工程或研究状态。

结论：`K0_ASSEMBLY_SOURCE_REVIEWED / ACTUAL_ARTIFACT_REVIEW_PENDING / NO_TIMING_PERMISSION_ISSUED`。
