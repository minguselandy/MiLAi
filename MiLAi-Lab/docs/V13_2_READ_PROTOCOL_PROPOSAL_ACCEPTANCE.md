# v13.2 读取协议只读方案的 Root 核对

Root 接受既有 Source owner 的盲只读方案交接，作为下一实现的设计输入；实现、机制执行和模型效果均未验收。原 Source 树 `v13-2-read-protocol-proposal` 保持 HOLD，HEAD `da33e6169c2745fbb50aee3f0a4370b9ceb1f02f`，tracked clean。

Root 第一份独立检查实际返回 0（tool `6ab0a9`）：逐 hash 核对 255 份索引原件和 7 份如实排除的终端/自引用控制，全部 262 份逐字节复制到 `artifacts/v13-2-read-protocol-proposal-source/`。38 个原始子进程回执全部返回 0，包含原 bootstrap 3 次、已完成索引 34 次和终端冻结 1 次；这只表示静态命令完成。每个原 stdout/stderr、原 before/after maps、driver 版本和实际索引项均匹配。21 份授权运行/工程测试快照、8 份归档官方方法原件及 AST 定义位置也核对吻合。

Source 原 `HANDOFF.md` SHA `04768b12f31b170a710cc6d8f87ecb7867b93f0185f4f502604bf6840c6b36d6`；`DESIGN.md` SHA `85a17c817ebb5e64597c0e85905b027f787642e5dd0207ccfc7c7ffe0a666d1c`；`source-checks.json` SHA `c9d851ffb95f34939f92ea1ffbd59e9eb2efbc6865dbbd750c3d86aa85c1995f`；file-index SHA `345bf4671d35cf4364008d79c9400384b5e46d5b538a16c2d0c576467c0b9a98`；原 manifest SHA `38c5a8a035b141bd04b3f1ab28772d0971bb6f4a2955081bd4add69d344766b3`。Root 独立证明 `artifacts/v13-2-development-r7/read-protocol-proposal-root-verification.json` SHA `796d558ea9faf7bdf517d6319f815a609bbb4d1596477c2a62b3a88154fd8c96`。

外部 bootstrap 写入违反原 only-new-tree 边界，事后仅接受原件保留/copy 的窄例外，仍按偏差报告。Root 另核对 16 份外部原件与授权新树副本完全一致且不变，证明 SHA `bbd7aa9fcc53af2927f3313bc8db0432beda019101ba50419ad4265a52b66976`。另一次原工具读取 `d97f93` 保留原输入/combined 输出，没有独立 stdout/stderr 或当时 maps，明确不可得、不倒补；它不混入 38 个原子进程回执。

Root 同意继续实现三个默认关闭、各自独立的候选：A 实际结果快照绑定，B 有限 typed 读取拒绝呈现，C 保存回执时序合同说明。A 的 exact Store key、短 digest 与完整 binding、合作 lock 和非 CAS 限制明确；B 不吞未知/权限/预算/CAS/冻结错误；C 不改原最终答复、不前移 writer、不添加生成或语义 verifier。公开 cursor 的 opt-in 字节变化要如实冻结，legacy 原字节保持；所有可见新增材料计入实际预算和后续真实成本。

主树/Source 原运行 212、测试 389、完整配置 316 的原件身份保持，连续 ledger SHA `374fcef4dd8a3082d352e2e936f68601edd65ba142880655349cfc68e652b15f` 未变。此次没有运行机制、SDK、pytest 或模型 HTTP；没有验证蕴含/泛化、四臂能力或有效独立评分。下一范围见[实现范围](V13_2_READ_PROTOCOL_IMPLEMENTATION_SCOPE.md)。原完整计划 ACTIVE、D4 NOT_ADMITTED、Product NO_GO。
