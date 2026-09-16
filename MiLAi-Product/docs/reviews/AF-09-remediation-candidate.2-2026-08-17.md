# AF-09 Candidate.2 整改记录

> 日期：2026-08-17（Asia/Shanghai）  
> 作者证据性质：`REMEDIATION_RECORD_NOT_INDEPENDENT_ACCEPTANCE`  
> Candidate：`1.0.0-candidate.2`  
> 当前 AF-09：`PENDING_INDEPENDENT_REREVIEW`

## 1. 不可变审查链

- Candidate.1 独立审查记录：`docs/reviews/AF-09-independent-review-2026-08-16.md`；决定为
  `REVISE`，包含 `AF09-F01`～`AF09-F10`。
- Candidate.1 archive 与 receipt 保持原样，不被 candidate.2 重锁或重写。
- 本记录只说明作者如何整改，不能把原决定改成 ACCEPT，也不能替代同一 reviewer 的 candidate.2
  全量复审。

## 2. 整改实现

| Finding | 关闭实现 | 关键直接证据 |
| --- | --- | --- |
| F01 | migration 0015：resolution submission noncanonical；approval 原子兑现，reject 保持 Issue | submission/reject、review revision-CAS tests |
| F02 | migration 0015：V1 `CREATE old=NULL`；Issue `ISSUE_CREATED NULL 0→1` | TX-02 creation/replay 与四类 history immutability |
| F03 | migration 0015：规范三轴 enum 与显式 legacy mapping | exhaustive accepted/mapped values；unknown atomic rollback |
| F04 | migrations 0017/0021：axis-complete ECS、Gate 与 Context single source | all-state-axis/confidence/valid-system-time integration test |
| F05 | candidate.2 crosswalk 使用精确 positive/negative test nodes | bundle validator coverage、missing-node/lock negative tests |
| F06 | migration 0016：TX-05 Proposal→mutation→Decision/event/outbox 同事务 | governed success 与 forced rollback no-residue tests |
| F07 | migrations 0019/0021–0023：typed erasure proof + built-in SQL SHA-256 | Blob tamper/symlink；forged proof dead-letter；already-absent retry |
| F08 | exact role DSN + open/ping/every-connection attestation | owner、swapped login、unsafe attributes/ownership tests |
| F09 | migrations 0018/0020 + causality domain/application | token tamper/wrong-key/cross-tenant/future、wait/fallback/snapshot tests |
| F10 | review/release external manifest digest | missing/mismatch/coordinated bundle+manifest substitution tests |

Governing decisions are ADR-015 and ADR-016. Candidate.1 deployment is upgraded forward-only through
`0023_complete_erasure_sha256_repair`; destructive downgrade across 0015+ is rejected because it would erase
governance/erasure audit facts.

## 3. Author verification snapshot

At remediation implementation completion:

```text
runtime real-role PostgreSQL suite: 92 passed
Alembic current: 0023_complete_erasure_sha256_repair
focused governance/security/retrieval/deletion suites: PASS
```

Candidate.2 bundle validation, full lock, archive digest and reviewer rerun are recorded separately so this
document cannot circularly attest its own final digest.

## 4. Independent acceptance condition

The same independent reviewer must obtain the manifest SHA-256 from the external candidate.2 receipt, run
`verify_lock.py --scope all --mode review --expected-manifest-sha256 ...`, inspect every F01–F10 closure and
write a new re-review record. Until that record says ACCEPT, this candidate remains `NO-GO`.
