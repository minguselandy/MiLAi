# AF-09 Candidate.1 Submission Receipt

> Submission：`MiLAi Logical Architecture 1.0.0-candidate.1`  
> Independent decision：`REVISE`  
> Preservation date：`2026-08-16`（Asia/Shanghai）

本 receipt 在进入 candidate.2 修订前保存 AF-09 首轮审查对象和独立决定。它不改变 reviewer
结论，也不把 candidate.1 标记为通过。

## Identity

```text
Candidate manifest SHA-256:
e7f12a5f5832adc49e9c73cb6374ca66ac3c524cdbfe53709862f0155c45aab7

Independent review record SHA-256:
b12c64be6aea41cfb62ba9d8501a4cfc31f73dda0a50146de7d2367ae98f4707

Deterministic submission archive SHA-256:
3febbb21cb7aa61def4bc3b554af6884dfd6cc4edd14e05bdda221472782ecdd

Archive entries: 111
```

Archive：`AF-09-candidate.1-e7f12a5f-submission.tar.gz`

归档包含：candidate bundle/manifest、manifest 声明的全部 bundle 与 source-lock 文件、以及独立
AF-09 review record。外部 Git 仓库正文不复制进归档；其 commit/status/diff identity 仍由归档
manifest 的 Git locks 表达。

## Review outcome

Reviewer：`/root/af09_reviewer_retry`（separate no-history sub-agent）  
Decision：`REVISE`  
Open findings：`AF09-F01`～`AF09-F10`，均为 P1。  
Candidate.1 disposition：`NOT ACCEPTED / NO-GO FOR SCHEMA FREEZE`。

后续 candidate.2 必须使用新 manifest digest 重新提交同一 reviewer；不得改写本 receipt、归档或
首轮 review record 来隐藏 finding 历史。

