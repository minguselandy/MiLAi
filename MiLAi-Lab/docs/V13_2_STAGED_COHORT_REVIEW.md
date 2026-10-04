# v13.2 逐轨迹审查与首次派发控制

Root 已接受[推进驱动](../tools/run_v13_2_staged_e0.py)的限定离线工程证据，允许后续新冻结 E0 使用；没有启动新模型 cohort。它落实原计划 12.3 的受影响运行停止规则。R7 的假语义保存是在全部 24 条轨迹终止后的完整复核才发现，这一检测时点和所有原始结果保持原样。

每次 `next` 只执行冻结顺序中的下一条未开始轨迹，返回 `REVIEW_REQUIRED`。Root 必须读取实际输出、来源、保存回执、业务状态与错误，再写显式开发诊断检查点，关联原 attempt receipt 和证据 hash。没有审查、原派发结果不明、账本或冻结身份改变时不能派发下一条。已发现或无法排除的泄漏、gold 污染、共享 owner 污染、假持久保存及原始结果破坏使受影响 cohort 保持 HOLD。普通失败只在 Root 明确确认后续任务独立并关联已保存的原始方法反思时继续；不会重新派发旧失败条目。

驱动核对自身 SHA、完整运行文件集合与字节、配置/输入/运行 manifest、Source HOLD、事前 GitHub 核对证明和原连续账本。实际域只接受既有 canonical ledger；缺失时拒绝，不建立替代零账本。首次派发前以独占创建方式保存 issued 与账本原字节、fsync 原件并写入 DISPATCHING。每次下一步重新核对所有已完成 attempt 的 stdout/stderr/issued/账本/原 process-results/receipt 文件闭包，以及已确认的审查和反思证据。每条轨迹的真实消息长度按冻结输入读取，缺失 final 不补造。

最终公共文件 SHA `561f493bbd770f08c67844faf5f79d6d233cc32379892daadb19d26f7a1fcc82` 对应 44 项本地控制、34 个隔离夹具，实际返回 0。夹具使用 stdlib 假 CLI、预先建立并明确标为合成的局部账本和 socket denial，没有 Lab/SDK 机制或模型调用。控制包含真实 24 次脚本子进程/48 条可变长度消息、失败后仅继续下一未运行任务、五类已发现 hard-stop、未解决问题暂停、原件/审查/反思改动拒绝，以及真实父进程在脚本记账后被终止。后者保留 DISPATCHING、unknown 和缺失 receipt，下一次拒绝重复派发。两个本地进程的父控制锁检查也通过。

最终同一公共文件的 ruff、strict mypy、package boundary 和 tools boundary 四项实际均返回 0，每项原 before/after 运行 212、测试 389、完整配置 316 和连续账本身份一致。Root 另逐字节核对原本地证据，最终核对命令实际返回 0（tool `22a79a`），证明存于 `artifacts/v13-2-development-r7/staged-controller-public-originals-root-verification.json`。[验收清单](../data/manifests/v13-2-staged-cohort-review-acceptance.json)保存所有公共身份、原命令来源、失败和控制标签；原日志、合成输出及账本保持 ignored，不提交 Git。

原首轮 32 项通过；扩展脚本首次返回 1，因为 Root 的局部替换没有匹配完整路径，仍加载旧驱动，stdout 改动控制准确发现缺少新闭包校验。修正引用的新脚本 44 项通过。公共代码首 ruff 返回 1（51 项）、首 mypy 返回 1（2 项）；保留原代码和原日志，再完成格式/UTC、显式原字节 close+fsync 与类型声明。最终公共字节重新验证 44 项。失败版本不覆盖：前后三组原件核对 2376 文件，公共阶段原件另核对；早期非完成静态命令没有单独序列化当时完整 maps，明确不可得，不用后来 maps 倒补。

此驱动只控制 Root 推进，检查点内容仍由 Root 手工复核；它不生成语义评分、不检查保存措辞、不提供独立 Judge，也不向模型注入 rubric、案例分支或新提示。父控制锁只覆盖同一 job，不能替代尚未实施的全部 client/原账本进程生命周期 HTTP owner。最终 `ATTEMPTS_COLLECTED_ROOT_REVIEWED` 明确不表示质量门槛或完整计划通过。

实际使用还须另接受通用 A/B/C Source 实现，准备全新空 cohort、完整 runtime/config/input/route/token/wire 冻结并核对 GitHub 事前发布，不能绑定 R7 重跑。本次新增真实生成/嵌入 0，ledger SHA `374fcef4dd8a3082d352e2e936f68601edd65ba142880655349cfc68e652b15f` 未变；48 项原状态保持，完整原计划 ACTIVE、D4 NOT_ADMITTED、Product NO_GO。
