# UA-08 Agent Integration Release Preflight

> 日期：2026-08-17  
> 候选：Agent Integration 0.1  
> 结论：`REVISE / DEVELOPMENT PREVIEW ONLY`

> **历史记录说明：** 本文件保留首次 preflight 当时的证据与 `REVISE` 决定，不应被当作当前
> candidate 状态。其工程缺口已在后续实现中关闭；当前候选入口是
> `UA-08-agent-integration-release-candidate-2026-08-17.md`，最终提升仍以独立 review 为准。

后续逐条审计发现，本记录的早期工程结论覆盖范围不足，不能支持 UA-00～UA-08 或 Beta DoD 全部
完成。权威缺口矩阵见 `UA-requirements-evidence-matrix-2026-08-17.md`；以下通过项仍是有效局部
证据，但不得合并推导为 release PASS。

## 已通过

- 安全 init：`.env` 0600、O_EXCL 不覆盖、独立 secrets、secret-free 输出；
- 全层 doctor/status 与隔离临时库全链 smoke：运行实例 PASS，PostgreSQL head
  `0027_embedding_identity`；
- Runtime Ruff/mypy；在全新专用 PostgreSQL 数据库最终全套 `135 passed`（76.22s）；
- Runtime unit/contract 48 passed；SDK 5 tests；MCP 3 profile tests；六个包 build 成功；
- real DB fresh base→0027；retrieval/worker integration 14 passed；
- Embedding benchmark：13 cases，hash 0.5385，ONNX 0.8462，绝对提升 0.3077；
- synthetic E2E：批准前 ABSTAINED；批准后 exact/semantic OK，FTS+vector 命中；
- MCP official client protocol `2026-07-28`，reader 精确 6 tools，recall OK；
- LangGraph review interrupt、AutoGen data-only recall 和 Blob 明文零命中验证通过。
- quiescent encrypted backup/verify/empty-target restore 完成：head/inventory 对账，正确 KEK 可恢复
  64-byte synthetic Evidence，错误 KEK fail closed；备份 manifest 明确 `key_material_included=false`。
- current-byte inventory：208 entries，secret 文件零纳入，entries root
  `31d5b1e18544ebafcfe924deae7d61fe3c2ff4b3d0363a6c9263d846316a3b55`。
- frozen bundle structural validator 仍 PASS。live `architecture/v1.0` 的旧 all-scope source lock 对
  18 个新 Runtime/Runbook bytes 报 drift，这是新 candidate 的预期变更证据；未刷新或伪造
  1.0.0 manifest/external anchor，冻结发布物继续由原 archive/receipt/独立 PASS 记录认证。

## 仍保持阻断

1. `LOCAL_PERSONAL_DATA`：AEAD/rotation 和工程恢复演练已通过，但用户批准与独立恢复证据接受
   尚未完成，因此 `.env` 保持 `SYNTHETIC_ONLY`/recovery-confirmed=false。
2. Remote MCP/Runtime 和 multi-agent identity/delegation：未批准。
3. Schema freeze/Production：未申请；仍为 EXPERIMENTAL/CANDIDATE。
4. UA-08 独立 Agent Integration review：待独立 reviewer 复核 current-byte inventory 与 E2E；
   在无开放 P0/P1 前不得把本 preflight 写成最终 PASS。
