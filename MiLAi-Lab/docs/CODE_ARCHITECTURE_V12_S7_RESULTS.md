# v12 S7：自动边界与最终验收

状态：本地工程验收与远端 Fast CI 完成，PR #76 已合并。源码基线为
`c8b7d81af54df65c4a74b720e7af1e359864cc4b`，S0–S6 均已保留独立提交。
语义实验继续暂停，Product NO_GO。

## 实际断点与范围

此前的 `boundary` 主要约束 Product/legacy import、绝对路径与 sys.path 修改；它尚不能
自动阻止 Lab 内部已明确的反向依赖。竞争解释是这些边界仅靠各阶段测试已足够，或后续
改动仍可能从嵌套导入、TYPE_CHECKING、动态入口和兼容 facade 中重新引入问题。现有检查的
覆盖范围支持后者，因此扩展现有门禁，而不是另建与 CI 分离的审计体系。

`application/recovery.py` 仍为 observer 的类型反向导入 baseline 实现。需要用真实调用所需
的最小结构接口表达依赖；不能只删类型或把导入藏进运行时。S7 不修改恢复动作、回执或授权。

## 实施边界决定

baseline 目录同时包含真实配方、观察设施与兼容入口，不能把整目录泛称底层服务，也不能
为了获得通过用 owner 标签改写依赖层次。对实际配方的同层关系单独说明，所有 baseline
到 runner 的反向依赖仍禁止。

通用 IO 与 Provider 的轻量记忆叶子只按已批准的精确路径允许，并检查叶子自身依赖。
有限常量/别名解析用于已有动态加载；无法确认的动态目标拒绝，不引入通用执行分析平台。

应用 journal/tools/recovery 原已由 Foundation explicit 命令严格检查。移除默认 discovery
中的对应排除项仅收敛扫描入口，不能称为首次检查这些实现。

## 本地验收结果

正式 DAG、纯 facade、canonical identity、实际类型覆盖、可选依赖和安装检查均已完成。
[精简工程证据](../data/diagnostics/code-architecture-v12/s7-engineering-evidence.json)
包含 13 个最终修改路径的 SHA、检查范围、初始失败和包身份。

- 初次组合 Core 检查为 204 项。随后发现禁止方向参数从待测规则生成，改为独立固定的
  90 个禁止方向和 11 个允许反控；最终受影响文件 199 项通过。两次范围重叠，不相加。
- Foundation 的 55 项身份漏项/篡改与实际恢复检查通过。
- strict Core 40 个文件、Foundation discovery 159 / explicit 67，以及 checker 4 个文件通过；
  这些范围相互重叠，不能加总为唯一文件数。External 五个未改接口复用 S3 检查。
- Ruff、boundary、tools boundary、verification matrix 与修改文件格式检查通过。
- 首轮分类缺口、执行器路径、Ruff/type、相对 level 负例与绑定作用域问题均修正；32 条检查
  记录中的 8 次初始失败保留。解析使用有限词法作用域，未知重绑定拒绝。

不重跑未受影响的 S3/S5/S6 SDK 与完整回放，不以机械检查宣称新增效果收益。
本地先通过十四项判据；C13 随修复后实现的远端 Fast CI 通过而完成。

## 源码、安装与保留证据

恢复函数的完整 AST 与 S6 相同，只增加实际 observer 所需的结构类型；无新校验、记录键或动作。
离线 sdist→wheel 已核对全部 194 个运行文件与工作树字节一致。新无依赖环境 `-I` 导入验证
Core 不加载可选 SDK，Foundation 的八个完整 facade 为同一对象；通用 Provider 对方法参数
的 `extra_forbidden` 使用合法 MockHTTP client 单独验证，未发起 HTTP。

最后的独立策略测试补充只修改测试数据和允许反控。最终 sdist 包含新测试，SHA 为
`452bd48ae6a8d605c4f0ba71c70cfd0d34adbe599dd97341921b4b140614aed0`；wheel SHA 为
`921b2b811ad0ff7dea42e82dc9b8cbc0b5b53cd864ddcbbf81bd3053d127e112`，与先前安装验证的
wheel 相同，194 个 runtime 文件字节相同。因此复用原隔离安装证据，没有声称再次安装回放。

[当前源码清单](../data/manifests/code-architecture-v12-current-import-map.json)
记录 194 个源文件和 1,895 个解析目标。S7 扫描器还计入 from-import 符号与动态表达式，
因此目标数不能与 S0 的 import statement 数直接比较；S0 清单保持原样。

[保留核查](../data/diagnostics/code-architecture-v12/final-preservation-evidence.json)
确认 190 份基线锁、结果/报告和 repair-v10 manifests 字节未变；Product/Archive 已跟踪实现
树未变，实验账本 SHA 为 `7f0e54548dcbebe1325ebbac4a0fc4441f20efc949cd16be4084c3f9b8aeda43`。
原 checkout 的 14 份与 repair-v10 的 9 份未跟踪草稿仍在，未将其作为新协议发布。
草稿仅作存在性/状态核对，没有迁移前哈希的文件不声称完成前后字节对照。

静态门禁覆盖有限常量、别名、相对/嵌套/TYPE_CHECKING 及已审查的固定外部加载规则。
它不宣称能证明任意生成 Python 代码的行为。既有外部 SDK 检查复用 S3 证据；没有新增
下载、真实模型调用或修改模型服务，旧实验失败继续保留。

## 首轮远端 CI 与最小修复

S7 提交为 `2ecd5630a5c0ce8ae3e19be9f20cdb5597835bba`，已发布至 [PR #76](https://github.com/minguselandy/MiLAi/pull/76)。
[首次 Fast CI](https://github.com/minguselandy/MiLAi/actions/runs/36595782771) 的 Lab、External、边界与实现一致性检查通过，
Foundation 因 CLI `run_unified_benchmarks.py` 对 TypedDict 使用动态键索引而失败，汇总 gate 随之失败。
本地同命令复现，排除了仅由 CI 环境差异导致的解释。

此前本地 Foundation 的 src discovery/explicit 检查未运行已有 CLI mypy 命令，矩阵检查也不能
替代实际执行这条命令。修复只增加标准库 Mapping 导入，将原 result 注解为只读
`Mapping[str, object]`；不转换返回对象，不改输出投影、字段、顺序或 producer。
实际 CI 五个目标的 mypy 命令与局部 Ruff 通过；擦除注解后函数 AST 相同，36 个模拟 CLI
场景的 stdout/stderr/调用/异常一致。未运行真实 benchmark，没有新增运行包模块变更，未重复构建。
[修复证据](../data/diagnostics/code-architecture-v12/ci-repair-evidence.json)保留首失败、修复及验证范围。
修复提交 `a944742ce786ac693c08ac69c4377f82a39afd09` 的 [Fast CI](https://github.com/minguselandy/MiLAi/actions/runs/36597268333) 全部必需组及汇总门禁通过。
[PR #76](https://github.com/minguselandy/MiLAi/pull/76) 已合并为 `48ad5439666d5398dff588b052dd80bd04e4ba4b`；C13 完成，首轮失败仍保留。
精确 job、实现身份及合并后核对见[发布证据](../data/diagnostics/code-architecture-v12/publication-evidence.json)。
