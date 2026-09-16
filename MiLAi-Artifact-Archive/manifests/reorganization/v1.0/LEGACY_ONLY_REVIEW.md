# Legacy-only Review

本表补充 `REORG_INVENTORY.jsonl` 中 7 个没有同路径 canonical counterpart 的 legacy 文件。
它们均有 owner、动作和可恢复证据；本次结构重组不做 behavior forward-port。

| Legacy path | Owner | Decision | Reason / preservation |
| --- | --- | --- | --- |
| `docs/releases/MiLAi-Logical-Architecture-1.0.0-release-receipt.md` | Archive | `ARCHIVE_AND_RETIRE` | 历史 release receipt，不是当前 Product 行为；原字节移入本目录 `preserved-user-work/reorganization/v1.0/legacy-only/`，SHA 见 inventory。 |
| `runtime/backups/ua-encrypted-20260817-184128/blobs/6308f532-4c79-41c6-bebb-1b1e3457125f/12/12ae12d3cd0bf6b7c6b74f0007cc0df36bd1d95b58af00482fe174873d79a8cf` | Archive | `MANIFEST_ONLY` | 加密 runtime backup blob；不进入 Product/Lab。原始 SHA/大小已记录；Git tag/history 保留恢复路径。 |
| `runtime/backups/ua-encrypted-20260817-184128/database.dump` | Archive | `MANIFEST_ONLY` | PostgreSQL backup，不是源码或测试输入；不提交 Archive raw byte，SHA/大小已记录。 |
| `runtime/backups/ua-encrypted-20260817-184128/manifest.json` | Archive | `MANIFEST_ONLY` | backup 元数据，不是运行时配置；不进入 Product/Lab，SHA/大小已记录。 |
| `runtime/tests/unit/test_dg22_accuracy_acquisition.py` | Lab | `ARCHIVE_AND_RETIRE` | 旧 DG22 harness 且依赖 legacy `evals`；精确字节移入 Archive preserved work，不作为 active test。 |
| `runtime/tests/unit/test_dg22_temporal_applicability.py` | Lab | `ARCHIVE_AND_RETIRE` | 旧 DG22 temporal harness；精确字节移入 Archive preserved work，不作为 active test。 |
| `runtime/tests/unit/test_sufficiency.py` | Product | `ARCHIVE_AND_RETIRE` | 旧兼容入口仅 re-export legacy `runtime.tests`/DG17 测试；canonical Product 已有 sufficiency tests，精确字节移入 Archive。 |

这些项目不是 UNKNOWN，也不是待自动合并的功能。若未来需要恢复一个测试或备份，必须以独立
变更说明、owner、测试和数据安全审查为前提；不得从 Archive 直接成为 Product/Lab import。
