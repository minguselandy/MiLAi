---
document_id: MILA-HOST-WORKSPACE-B-DISPOSITION
date: "2026-09-13"
status: B_STOPPED_NO_READY_ISOLATED_TASK_ENTRY
experiment_kind: RESEARCH_PROTOTYPE
root: terminal-bench/cancel-async-tasks
model_requests: 0
checker_runs: 0
second_source_comparison_completed: false
reviewer: delegated_development_agent_not_human_gold
---

# W3 有界处理：停止本轮 B，继续 A

依据 [Goal 第 7 节](MILA_HOST_WORKSPACE_开发与行为探索_GOAL_v1.0_20260913.md)的停止选项，本轮不运行 B。官方任务源码可读取，但本次有界检查没有找到可直接复用、已验证的独立任务执行入口。构建新沙箱及 Python 3.13 任务环境会把准备工作扩大为另一项工程。由用户授权的 subagent 完成此开发处置；不称人工或独立 human gold 审批。

这不是任务本身不可解、内核不能隔离或模型能力失败的证据。B 未产生实现、正式 checker 正负例或三臂轨迹；第二来源比较**未完成**。不选择事后替代题，不把 B 的 72 次配额转给 A。B 不阻塞 W1/W2。

## 实际检查

检查基于 Lab HEAD `97aa5947cd4befe37beb63856d167727dd282e9c` 的工作树；未执行容器、GPU、共享服务或模型生成代码。

| 检查 | 实际结果与含义 |
| --- | --- |
| 在 `/cra/memory/mx_memory/benchmarks` 与 `MiLAi-Lab/artifacts` 递归查找 `cancel-async-tasks` 目录 | 均为 `[]`；不能证明整个文件系统没有副本，只确认这两个既有数据位置没有任务包 |
| 搜索 Lab `src`、`tools` 的 sandbox / unshare / bwrap 入口 | 当前 `tools/v0222_scoped_cpu_guard.py` 明示仅阻止当前 Python 进程 socket audit，不是任意 native code 或 subprocess 沙箱；不能给 B 使用 |
| 只读检查旧 `MiLAi/evals/agent_efficiency/provider_sandbox_exec.py` | 用 mount、Landlock、降权和固定文件描述符执行 provider adapter，要求专用 launcher 参数；不是已接好的可写任务/checker 环境。Lab AGENTS 禁止把 legacy 模块变成活动依赖，未导入或启动它 |
| `shutil.which` | `bwrap/nsjail/firejail/podman/python3.13` 为 `None`；`unshare=/usr/bin/unshare`，`docker=/usr/bin/docker`。仅查二进制路径，未查询或启动 Docker daemon |
| 无害能力探测 `unshare --user --map-root-user --net /bin/true` | exit `0`，stdout/stderr 空。证明可以创建该组 namespace，**不证明文件系统、凭据、设备、进程与资源限额已经隔离** |
| 运行时版本 | `unshare from util-linux 2.37.2`；`python3 --version` 为 `Python 3.10.12`；初次 `python` 命令不存在，随后使用 `python3` 完成检查 |
| 官方入口只读检查 | `tests/test.sh` 需 apt/curl、uv 0.9.5、Python 3.13、pytest 8.4.1、pytest-json-ctrf 0.3.5，并复制 `/tests/test.py` 到 `/app/test.py`；未安装、未执行 |

官方 `task.toml` 声明 1 CPU、2048 MB、0 GPU、900 秒 agent/verifier timeout，镜像 tag `alexgshaw/cancel-async-tasks:20251031`，并允许联网。Dockerfile 使用 `python:3.13-slim-bookworm`。这些是上游配置，不是本轮资源授权或已固定镜像 digest；本轮没有拉取镜像。准备恢复时须提供实际隔离入口，并将联网能力与 Goal 的有限执行权限对齐。

官方测试源码检查正常并发、并发上限及任务数低于/等于/高于上限时 SIGINT 后的清理；辅助任务的 `finally` 包含实际异步等待。尚未本地执行 checker，因此没有证明它能区分本轮明显正/负实现，也没有官方成绩。测试含计时及输出计数，若后续执行还须核对实际代码和回调副作用，不能把目标字符串视为充分证据。

## 已核对版本与内容 hash

通过 GitHub commit API 解析 main，随后按固定 commit 读取所列文件：[官方仓库版本 `2fd12b88aafdd04a52c298e3940bcb189f9766d6`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/cancel-async-tasks)。以下 SHA-256 是本次 HTTPS 实际读取的字节；没有建立本地任务包。首次读取 `test_outputs.py` 遇到 TLS EOF，第二次固定版本读取成功，未由失败推断源码不可取得。只读下载没有模型调用。

| 文件（任务目录相对路径） | SHA-256 |
| --- | --- |
| instruction.md | `23d22f7039b50682941652c716f96dac314b8585c32c133614cac77dc067f47e` |
| task.toml | `14db0675e04408f2133b0067e8dbddf66a1d6e7baf6b8d38bef8ecccfc4e58a8` |
| environment/Dockerfile | `1ee7bdb4a7536f5f114c11a3ac6ff42790abfea901fcba6b2a8ea8685f19140e` |
| tests/test.sh | `79600a6b863def31b4daa008297423010cd2d6243e689d67503e118e4dc53397` |
| tests/test_outputs.py | `d6f510b51fafc81b4e9b5cc95535aa13491c8753e0e4171db42c45f4de460ee7` |
| tests/test.py | `f533c0a64db068f582b4733c5b81f2e66b8fa52fcd3efa65752e6bd6d24780aa` |
| 仓库根 LICENSE（Apache License 2.0） | `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |

本地只读核对 hash：`v0222_scoped_cpu_guard.py` 为 `338972bec63c9fff56b87e2e0cd9a4daaf34aa20f8dcd01e4dd204d91e11bc14`；旧 provider sandbox 为 `f3d48c0652500f46ca40f9fedcb4c9dced4a63d70e2a46bf31e150d2c4ea73c4`；`/usr/bin/unshare` 为 `cc4efe90b92a81316a980ccbc1b8114c9f450aa1da65f2b1d4dedd5b2b3345ca`。

## 后续触发条件

只有出现可复用的独立任务环境时再恢复 B：在该环境固定以上任务版本及必要运行时，验证真实 CPU checker 正负例，再登记同初态三臂比较。当前不创建新执行平台，不执行 `/app` 任务，不借临时目录代替隔离。此次修改仅为处置文档，检查文档格式和链接，不触发完整代码回归。
