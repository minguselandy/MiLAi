---
document_id: MILA-LAB-PRODUCT09-INTEGRITY-AUDIT
version: "1.0"
status: PROVISIONAL_FAIL
reviewed_at: "2026-09-03T21:13:00+08:00"
review_independence: same-family
acceptance_status: provisional
overall_verdict: FAIL
reason_code: CLAIM_EVIDENCE_MISMATCH_AND_UNSEALED_EVALUATION
---

# Product-09 审计不可变摘要（Product-10 继承门）

七个 result JSON 均存在、可解析且算术可复算，但 restart、formal access、turn-label provenance、
tool isolation、cleanup 与 run-to-pin/input binding 不满足 audit-grade control 要求。

允许继承：一份四例 opened-development run 的 normalized EM/F1 `3/4 / 0.75` documentary
observation，非官方 scorer；不允许继承为 effect baseline 或 memory causal claim。Product-10 必须
先重跑 sealed A0。完整 A--F、claim impacts 和 actions 见同次稳定报告 `EXPERIMENT_AUDIT.md`；
原始 reviewer response 见 `.aris/traces/experiment-audit/2026-09-03_run01/`。
