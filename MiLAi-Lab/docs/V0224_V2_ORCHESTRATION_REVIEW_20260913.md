# V0224 v2 编排代理审查

审查者：Codex subagent `/root/gate_review`，非真人。此次比对 v1/v2 编排六文件，未创建或运行实际 fixture，未改任何 runtime 源码；仅新增局部编排测试。

CPU binding 仅把固定 base 改为 `20260913-gate-a-v2`，root basename 增加 `v2-`，coordinator revision 改为 V2。构造/授权 AST 与 v1 一致，所有继承动态方法仍为同一函数。旧 root 被新授权构建器拒绝；原期限、额度、旧未知账及零 HTTP 标志没有放宽。

Fixture 继续使用原历史 CPU manifest 的输入、依赖与 executed-source 副本作为完整负担，原 public leaf 经已 pin presentation binding→manifest 取得。新增 entries 包含实际 v2 binding、fixture、worker、prefix helper、parent、inventory，以及原 coarse observer。路径映射为 `v2-k1-u1-p3-01`、`v0223-v2-k1-u1-p3-01` 等；assembler 用 `root.name` 校验这些字段，避免拿不带 `v2-` 的选择器误验。新增业务值映射仍只允许 ID/scope/派生初态 hash。

Worker 只导入 v2 prefix helper，并显式传 `observe_internal_timing=args.mode == "S"`；parent 只调用 v2 worker，六位置顺序与每子 300 秒保持原样。该参数接线已核验；helper 内部是否严格禁用 U 观测时钟由另一代理的专门测试和最终封存审查验证，不能只凭参数存在宣称 v1 blocker 已彻底解除。

局部检查 `uv run --offline pytest tests/unit/test_v0223_v2_orchestration.py -q`：13 passed，涵盖 v1 root 拒绝、错误选择器、动态代码不变、public pin/封存 guard 不变、实际 v2 entries、worker/parent 接线和 assembler 的 v2 ID 映射。JUnit：[本地记录](/cra/memory/mx_memory/evidence/v0224/20260913-a-k0/v2-orchestration-local-tests.xml)。首次 Ruff 指出测试文件初始化变量影响导入顺序，已调整；Ruff check 通过。

结论：`V2_ORCHESTRATION_LOCAL_CHECKS_PASS / ACTUAL_V2_FIXTURE_AND_K0_REVIEW_PENDING`。本记录不签 K0、K1、A1/A2 或 Gate A PASS，不复用 v1 七目录的执行资格。
