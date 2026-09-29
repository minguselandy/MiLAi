# GitHub 合并与代码结构整理

2026-09-29。用户明确要求整理 GitHub 提交、完成仓库合并并梳理代码结构。
这次授权覆盖旧阶段的“不合并 main/旧 PR”限制；原研究 Goal 仍为 **paused**。
Sol xhigh 负责唯一一项必要代码修复，Luna high 执行 Git 发布与合并，Root 负责文档和验收。

## 合并结果

合并前远端 main 为 `07cc364f96d484ad9ff8497adcf2a6f1b486bdb2`。
依赖链按 #70 → #71 → #72 → #73 → #74 合并，每个后继 PR 先改 base 为 main 并核对层内差异。
使用 merge commit，保留原始开发、冻结与报告提交；未 squash、rebase、force push 或删除分支。

| PR | 内容 | 原 head | 合并提交 | 合并前 Fast CI |
|---|---|---|---|---|
| [#70](https://github.com/minguselandy/MiLAi/pull/70) | v6 请求上下文与结果 | [c6f335f](https://github.com/minguselandy/MiLAi/commit/c6f335fef7cf00c86fa3dbe201a60c802439ca12) | [b7cdc2d](https://github.com/minguselandy/MiLAi/commit/b7cdc2d2e565ad7defab37db33f43bab9aad4c01) | [成功](https://github.com/minguselandy/MiLAi/actions/runs/36411545487) |
| [#71](https://github.com/minguselandy/MiLAi/pull/71) | v7 协议与实验记录 | [77dfc2f](https://github.com/minguselandy/MiLAi/commit/77dfc2f43f2307bb649cdbee9d62a97e5863fac0) | [0cc47ec](https://github.com/minguselandy/MiLAi/commit/0cc47ec7d742263ee5710c1785b88bc36ea80b48) | [成功](https://github.com/minguselandy/MiLAi/actions/runs/36426398229) |
| [#72](https://github.com/minguselandy/MiLAi/pull/72) | v8/v9 原生比较与暂停报告 | [983669d](https://github.com/minguselandy/MiLAi/commit/983669dd2d0bfbf26f212b6adf2c51d7de535552) | [fbed0a7](https://github.com/minguselandy/MiLAi/commit/fbed0a73ce3a8c4c206c9bd9b07a931ab4e00e02) | [成功](https://github.com/minguselandy/MiLAi/actions/runs/36498593784) |
| [#73](https://github.com/minguselandy/MiLAi/pull/73) | v10 修复开发与失败报告 | [091dcbd](https://github.com/minguselandy/MiLAi/commit/091dcbd48dc1800e5b8cc7f0ee3066dc00a76311) | [a009df1](https://github.com/minguselandy/MiLAi/commit/a009df151aa3212d7a7141719dbf3cdf28169cc6) | [成功](https://github.com/minguselandy/MiLAi/actions/runs/36527804538) |
| [#74](https://github.com/minguselandy/MiLAi/pull/74) | 应用模块拆分、导航与兼容导出修复 | [97efe0c](https://github.com/minguselandy/MiLAi/commit/97efe0c997b37022f21905cff63f69cb480527a8) | [8781ad7](https://github.com/minguselandy/MiLAi/commit/8781ad798184040da2e4c48550b993915dcbe0db) | [成功](https://github.com/minguselandy/MiLAi/actions/runs/36533341622) |

开发链整合后的 main 为 `8781ad798184040da2e4c48550b993915dcbe0db`。
它与 #74 最终 head `97efe0c997b37022f21905cff63f69cb480527a8` 的完整 Git tree 均为
`e9ddc479320b76bb6167bfc7d7a172ff73c42f27`。因此整合没有引入额外内容差异。
上表各原 head 和对应历史冻结提交继续可达。本记录及根导航是此后独立的纯 Markdown 收尾。

## 旧 PR #51 的处置

[PR #51](https://github.com/minguselandy/MiLAi/pull/51) 已关闭为被后续工作替代，**未标为 merged**。
它的两项改动已通过后续提交进入合并前的 main；stable patch-id 和祖先关系均已核对：

| 原提交 | 已合入的等价提交 | stable patch-id |
|---|---|---|
| `26c4f3058691af3fe31cda906f67ffce6bd1986f` | `8337bb6dd233b88f2377e5b7a0a81f122be0e325` | `3b2eff4dde96f77a0d73c2df8983024dbe196e1d` |
| `055a0769c1ce75d128d6459ee25773587d9003ae` | `5dc024d3b277915709556af4e3eee4e1e64f06f1` | `37b41094f6b9e5eaf58db8eaeeac26657dc67e58` |

保留原 body、失败 CI 和分支，只追加已被替代的说明；没有重新合入冲突的旧版本。

## 必要 CI 修复与验证

#74 原 head `bfd22e1` 的 Foundation CI 发现：共享记录模块导入旧 runner 的 `_business_tools`
时，strict mypy 不认可隐式私名导出。运行时对象与函数体仍一致；首断点在导出声明。
Sol 仅将导入改为 `_business_tools as _business_tools`，保留同一 canonical 函数对象。
4 个消费者文件的 mypy、单文件 Ruff、旧入口/共享/持久消费者的对象一致性检查均通过。
原 31 项局部测试、AST/Golden 和离线构建证据保留，没有为发布重复运行。

[修复补充清单](../data/manifests/architecture-merge-ci-fix-20260929.json) 保留当时的本地验收与等待远端状态；
其后 `97efe0c` 的 [Fast run 36533341622](https://github.com/minguselandy/MiLAi/actions/runs/36533341622)
已 completed/success：8 个 job success、4 个按条件 skipped，包含 Lab core、Foundation、external 与最终 gate。
原失败日志继续保留。Full composition 按既有标签/手动触发规则 skipped，**不是通过**。
没有修改检查门禁、可选依赖合同或实验默认参数来放行。

## 代码结构和入口

- 根目录：[README](../../README.md)、[仓库地图](../../REPO_MAP.md) 负责跨目录导航与治理。
- Lab：[项目地图](PROJECT_MAP.md)按任务定位源码，[架构说明](LAB_ARCHITECTURE.md)说明依赖方向。
- `application/`：world、journal、tools、recovery 的单一实现；轻量包入口不加载模型 SDK。
- `runners/`：阶段顺序、writer 时机、运行资源和交接；旧导入继续兼容。
- `methods/`、`baselines/`、`providers/`：分别维护记忆呈现、Agent/参考方法和模型协议。
- `docs/` 与 `data/manifests/`：设计、结果和身份；`artifacts/` 为忽略的本地运行材料。

没有移动 Product/Archive 实现，没有迁移数据库、Schema、权限或公开业务行为。
旧大 runner 和外部 SDK 的历史耦合仍按实际需要处理，不宣称全仓已完成统一分层。

## 暂停与保留

实验 Goal 仍 paused；R2 错误业务事实真实持久化的问题尚未解决，Product 仍 NO_GO。
[v10 总体报告](MILAI_REPAIR_V10_OVERALL_EXPERIMENT_REPORT_20260929.md)、原分数、未知项、冻结锁和失败均保留。
本次真实 Host、embedding、Judge 调用为 0；未下载模型资产或调整服务。
连续账本仍为 6,145 次 generation、11,407,086 generation tokens、416,930 embedding tokens，
SHA256 为 `7f0e54548dcbebe1325ebbac4a0fc4441f20efc949cd16be4084c3f9b8aeda43`。

原 main checkout、各旧 worktree、repair-v10 的九份未跟踪草稿及原 v27 草稿保留。
新的收尾 worktree 为 `/cra/memory/mx_memory/MiLAi-worktrees/merge-closeout-20260929`；
没有 reset 或覆盖旧工作目录。回查整合前主线使用 `07cc364`，实验复现使用各自冻结提交。
