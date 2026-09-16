# ADR-022：Embedding Provider 与质量门

> 状态：`ACCEPTED FOR EXPERIMENTAL IMPLEMENTATION`  
> 日期：2026-08-17

## Decision

检索依赖 `EmbeddingProvider` protocol。确定性 16 维 hash 仅保留为离线 fallback/test baseline；
真实 provider 必须显式配置、禁止 import-time network，并以 provider/model/dimension/normalization/
code-version 组成 projection identity。不同 identity 的 score 禁止混合。

首个真实 provider 是可选的本地 SentenceTransformer adapter；未安装、未配置或加载失败时必须
显式降级，L0/FTS 继续工作。只有在版本化本地 benchmark 上相对 baseline 有可重复提升且目标设备
性能达标后，才可成为默认质量路径。外部 API embedding 必须另行通过隐私 opt-in。
