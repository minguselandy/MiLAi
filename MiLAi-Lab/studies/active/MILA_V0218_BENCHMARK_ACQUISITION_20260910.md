# V0218 固定来源下载账本

状态（2026-09-11）：3 个代码/任务仓库及 WMA 全量数据均完整下载并逐文件匹配固定上游内容哈希。
这些是资源获取记录，不是 benchmark 成绩、模型可见性或任务成功证据。

统一位置：`/cra/memory/mx_memory/benchmarks/v0218-pinned`（Git 外）。

| 制品 | 固定 revision | 文件数 / 字节 | 状态与许可标识 |
| --- | --- | --- | --- |
| ClawMark 代码、100 task 目录及资产 | `d1b641b3171e584e69a3763c269069f32a13b574` | 1,996 / 813,834,112 | Git blob 全部匹配；CC BY-NC 4.0 |
| WMA 代码 | `15ea25b723d9c4fb35e8062037aec6a5601e4442` | 671 / 26,506,677 | Git blob 全部匹配；MIT |
| WMA HF 全量数据 | `e2148757921fc7e2d66d8ed899823b763227c341` | 16,059 / 9,959,668,254 | Git/LFS 内容哈希全部匹配；数据卡 CC BY-NC 4.0 |
| Supersede 仓库 | `677993d3713c265329ac935262d3c08cbfa4cd63` | 34 / 735,141 | Git blob 全部匹配；Apache-2.0 |

来源分别为 `evolvent-ai/ClawMark`、`UCSB-AI/WorldMemArena`、
HF `LCZZZZ/WorldMemArena`、`Vrin-cloud/supersede`；保持 V0217/Goal 的既定 pin，未切到最新 main。
MemTrapBench 官方匹配制品仍 HOLD，本次不替换成同名仓库，也不作为其余下载的阻塞门。
下载不会执行第三方 task.py，不打开确认池正文/gold，不把 89 个附件引用算成图片实际呈现。

上游树完整性记录位于统一目录下 `github-upstream-verification.json`。
每仓库 `*-files.json` 保存本地 SHA-256 清单，`*-status.json`/`download-attempts.jsonl` 保存下载账。
WMA 上游目录分页完整枚举在 `wma-upstream-files.json`，总量不从磁盘大小估算。
`wma-download-progress.json` 仅核对当前已有文件的大小，不能替代内容校验；
完成后须以 `wma-upstream-verification.json` 的 `UPSTREAM_HASH_VERIFIED_COMPLETE` 为准，
对 LFS 比较上游 SHA-256，普通文件比较上游 Git blob，不能只对本地文件自己算 hash 就称来源匹配。

最终下载进程正常退出，`wma-data-status.json` 为 `SNAPSHOT_DOWNLOADED_HASHED`；
独立全量核验已返回 `UPSTREAM_HASH_VERIFIED_COMPLETE`，verified_files=16059、
verified_bytes=9959668254、mismatches=[]，观测 Unix 时间 1789060546.780477。
三个代码仓库也再次逐文件匹配既定上游 Git blob。下载进程已结束，无凭据落入这些制品。

用户提供的 `hf.env` 只在下载进程内解析，不 shell source、不进入模型请求/仓库/日志；文件权限 0600。
下载使用 HF SDK 的参数传递 token，不打印凭据或带签名 URL；异常对外仅记录类型。
缓存与未完成文件保留，断点续传不视为新实验样本。
在确认总清单 16,059 文件、12 worker 已运行 22 分 30 秒后仅完成 4,908 文件/1,260,657,113 字节、
磁盘仍有 579 GiB 余量后，单独将下载并发修订为 32；模型生成仍串行。

可用命令（从 Lab 运行；不含 token 值）：

```bash
uv run python tools/verify_v0218_benchmarks.py --root /cra/memory/mx_memory/benchmarks/v0218-pinned --kind progress
uv run python tools/verify_v0218_benchmarks.py --root /cra/memory/mx_memory/benchmarks/v0218-pinned --kind verify
```

完整 Goal 仍见 [V0218](MILA_V0218_行为真值测试床建设_GOAL_20260910.md)，
实验接线与失败记录见 [执行合同](MILA_V0218_TESTBED_CONTRACT_20260910.md)。
下载完成不表示 12-source 测试床或 E0–E5 完成；目前状态见
[E0 v4 进度](MILA_V0218_E0_V4_20260911.md)。
