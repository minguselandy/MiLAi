# ADR-023：Self-hosted vLLM Validation Lane

> 状态：`ACCEPTED FOR LOCAL SELF-HOSTED EVALUATION`  
> 日期：2026-08-20  
> 数据边界：`SYNTHETIC / DEIDENTIFIED ONLY`

## Context

DG-10 的原始 `OE-F06/PVG` 链要求外部计费 Provider、原生 request ID、receipt 和上游
billing export/invoice 一一对账。用户在 2026-08-20 明确选择已运行的本地 vLLM，禁止
调用外部模型 API，并要求不修改 vLLM 的启动或配置，只调用现有实例。

自托管推理没有上游 Provider 账单对象。将本地 usage 或自计算成本冒充成外部账单，
会违反 DG-10 的明文边界。因此需要一条独立、可复核、不改写 frozen logical
architecture 的 `PV-LOCAL` 验证链。

## Decision

1. 新增 `Self-hosted Provider Validated / PV-LOCAL` 实验门，不替代、不降级也不关闭
   `OE-F06` 或 `PVG-00..04`。
2. 只调用用户已启动的精确 vLLM 实例。MiLAi 代码不启动、停止、重启、升级、
   更换、重标记或修改该容器、模型目录、启动参数和 GPU 分配。
3. 同机 A/B 调用端点精确限定为 `http://127.0.0.1:7860`。隔离的 OpenWorker
   adapter 只能从其专用 Docker 网络经宿主 bridge `http://172.17.0.1:7860` 到达同一个
   已发布实例。两种调用器都禁用 proxy、redirect 和 DNS，拒绝不同 port、HTTPS、
   userinfo 或额外 origin；adapter 只转发 `/v1/models` 与 `/v1/chat/completions`。
4. 运行前后必须重新验证：容器 ID/StartedAt/restart count、image digest、vLLM 版本、
   OpenAPI digest、served model ID、启动 argv、model mount、57 个模型文件 SHA-256 闭包、
   tokenizer/chat template/config/quantization 与实际 GPU UUID/driver。
5. 冻结 `provider_ab_workload.json` 的 500 turns × baseline/optimized，产生精确 1,000 次
   本地 inference。本地调用器对两个 variant 统一附加不含 case 答案的 reason-code
   语义表，并用 closed JSON schema 约束结构；其文本/schema 单独哈希入证。
   每次先用同一 vLLM tokenizer/chat template 计数，必须与生成回应
   `prompt_tokens` 相等。
6. 只保留逻辑/native request ID、模型 ID、usage、finish state、normalized 五字段输出、
   hash、质量、安全与时延；不把 raw Prompt/memory/model output 写入报告。
7. vLLM 输出仍是 `trust=data-only`，不得直接写 Claim/OpenIssue/Decision/Canonical table；
   Evidence → Proposal → Decision → Canonical Procedure 不变。

## PV-LOCAL gates

| Gate | 判定 |
| --- | --- |
| `PVL-00 Target Identity` | 现有实例、image、model closure、tokenizer/template、argv、GPU 精确绑定 |
| `PVL-01 Local-only Route` | 1,000 次调用全部只到 `127.0.0.1:7860`，外部 Provider requests/cost 均为 0 |
| `PVL-02 Token Truth` | 每次 `/tokenize` 预计数与生成 usage 精确相等，输出不超上限 |
| `PVL-03 Same-model A/B` | 100/500-turn 质量、安全、token、round trip 和 wall time 门完成 |
| `PVL-04 Agent MCP E2E` | 同一 vLLM 与 OpenWorker/MCP 冻结链路重放 S1～S10 |
| `PVL-05 Independent Review` | fresh reviewer 验证身份、调用、故障、隐私和回滚证据 |

`PVL-00..04` 的作者报告最高只能是 `LOCAL_CANDIDATE_REVIEW_REQUIRED`。`PVL-05`
之前不宣称 `PASS`、Beta 或 Production。

## Observed target boundary

- vLLM `0.27.1`，image ID
  `sha256:e0cfcfcb9b86e2c2d0d52a93689773f20f380cb8e050a24ce550c44f6f55c5eb`；
- image repo digest
  `sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967`；
- served model `Qwen3.6-35B-A3B-FP8`，model closure
  `115760819d0006a4d3c05f5722fc89a8b536f63dd5047a73555178e9162ede19`；
- identity binding
  `951564832a9bd75c927b42583a0ee66a688b78aea8a247bd72835cef1db84500`；
- 2× NVIDIA A100-PCIE-40GB，TP=2，driver `580.178.04`。

完整观测对象见
`docs/reports/DG-10-vllm-local-identity-2026-08-20.json`。

## Known risks and consequences

- 现有 vLLM 端口由用户以 `0.0.0.0:7860` 发布，且未配置 API key；本 ADR 不授权
  修改该启动，MiLAi 只从 loopback 调用并将此列为既有风险。
- `/cra/qwen36-35B` 以 read-write bind mount 提供给现有容器。运行前后全文件复哈希
  可发现漂移，但不能把可写启动边界表述为已加固。
- 共享 GPU 上的其他进程可影响 wall time，时延只是本次观测，不是 SLA。
- 自托管 cost 为 `NOT_APPLICABLE`，不得用 `0 USD` 的自计算记录伪造上游 billing truth。

## Status language

PV-LOCAL 通过独立复核后允许的最高表述是：

```text
MiLAi has passed one exact self-hosted vLLM same-model local validation for
synthetic/de-identified workloads; external-provider billing validation OE-F06 remains open.
```

## 2026-08-20 execution disposition

The lane was executed without changing the vLLM lifecycle. Candidate.1 truthfully retained its
`FAIL_COMPLETE` result at 353 tool-schema tokens. Candidate.2 then removed model-controlled
consistency/limit from reader-lite, bound both in the Host, rebuilt and offline-tested the package
closure, and completed a fresh exact 1,000-call capture. The bound Qwen tokenizer now measures the
query-only reader-lite schema at exactly 250 tokens; every completed A/B gate passes. Candidate.2.4
also completed OpenWorker/MCP S1-S10, recomputed the complete A/B prerequisite, and passed exact
post-discovery restart config/catalog checks.
These remain author-generated local candidates: `PVL-05` and `OE-F06` remain open, so the external
Provider/Beta success statement is still not applicable.
