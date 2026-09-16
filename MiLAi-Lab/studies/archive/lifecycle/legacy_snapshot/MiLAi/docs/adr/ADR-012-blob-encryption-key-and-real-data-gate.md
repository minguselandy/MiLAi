# ADR-012：Blob Encryption、Key 与真实数据门

> 状态：`ARCHITECTURE ACCEPTED / IMPLEMENTATION REQUIRED BEFORE REAL DATA`  
> 日期：`2026-08-16`  
> 当前数据门：`SYNTHETIC DATA ONLY`

## Context

当前 `LocalContentAddressedBlobStore` 使用 tenant-scoped SHA-256 CAS、0600 文件和 0700 目录，但
正文仍为明文。文件权限不是静态加密，不能支撑真实个人数据 gate。

## Decision

- 逻辑 Blob identity 仍为 tenant + blob ID；content hash 只用于完整性/tenant 内 dedup，不授予权限；
- production artifact 使用版本化 envelope：随机 per-blob DEK、AEAD（AES-256-GCM）、唯一 nonce，
  AAD 绑定 tenant/blob/content-hash/media-type/length；
- DEK 由 per-install KEK 包装，KEK 只来自 OS keyring/受控 secret provider，不进入数据库、备份
  manifest、日志或仓库；
- `key_reference` 只保存非敏感 key version/reference；rotation 采用 rewrap，必要时显式 re-encrypt；
- backup 保存 ciphertext 与 wrapped DEK reference，restore 必须先验证 envelope/hash，再授权解密；
- crypto erase 不能替代 GroundingBlock、projection purge 和 backup obligation；
- tenant 间禁止 Blob dedup。

## Required implementation gate

在 envelope format、schema/migration、key rotation/recovery、tamper test、backup/restore 和丢 key
演练完成前，MiLAi 只允许 synthetic fixture，不得导入真实个人数据。当前 plaintext Blob 不做
静默原地加密；使用 staged copy、hash verify、atomic pointer switch 和可回滚 migration。

