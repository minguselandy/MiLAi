# DG-20 ResidualCue v0.2 与制品边界

`ResidualCue v0.2` 只表达“搜什么”。Runtime 在接收 cue 前已经固定 channel、scope、时间边界、
source policy、candidate cap、expansion policy 与 completion policy；cue 既不是 action，也不拥有
Evidence、Binding 或 Sufficiency authority。

## Wire contract

允许字段只有 `requirement_state_digest`、`target_requirement_id`、`aliases`、`phrases` 和
`morphological_variants`。Runtime 拒绝答案、`COMPLETE`、Evidence accept/reject、scope/authority/
permission 变更、channel 选择、cap 扩大或 retry 指令。目标 requirement 与实体边界仍必须由 Runtime
对当前 immutable QueryIR 和 unresolved RequirementState 校验，不能从 cue 文本自行扩张。

## Restricted artifact

精确 cue 只能写入受限加密制品。持久化 envelope 必须记录 cue digest、ciphertext、ciphertext digest、
`AES-256-GCM`、租户 key reference、创建时间与明确的 retention deadline；不得把明文 cue、Prompt、
Evidence 正文、token 或 secret 混入公开目录。

## Public receipt

公开回执只保存 RequirementState/Capability/cue digest、三类表达式计数和 typed reason。验证者即使无权
读取 restricted artifact，也能验证 digest chain。DG-20 当前未进入 S3 entry gate，因此不生成精确 cue，
公开处置固定为 `DISABLED_NOT_NEEDED`，Provider calls、retry 与 additional cue pass 均为零。
