# MiLAi Agent Rules

本文件只规定单仓库的跨 bundle 工作规则。具体产品、研究和 Archive 命令以各自目录的
README、`pyproject.toml`、锁文件和 CI 为准。

## 权威顺序

1. `SOURCE_OF_TRUTH.md`、`REPO_MAP.md` 和本文件的边界规则；
2. `MiLAi-Product/` 的公开契约、迁移、真实测试和产品文档；
3. `MiLAi-Lab/` 的研究协议、锁定 Product 身份和独立结果；
4. `MiLAi-Artifact-Archive/` 的 manifest、catalog、SHA-256 与历史证据；
5. Git tag/history 中的 legacy 文件只作为恢复和差异输入。

同名或相似文件不表示相同语义。legacy 不自动正确，也不得整体 merge 回 Product/Lab。

## 依赖边界

- Product 可以依赖自己的 `runtime`、公开 contracts 和 integrations；禁止 import `MiLAi-Lab`、
  `MiLAi-Artifact-Archive`、根 legacy 包或研究/评测代码。
- Lab 只能通过 Product 的公开 MCP/client/contract/testkit 使用产品，并在 study manifest 中
  记录 Product commit/manifest/SHA；禁止导入 Product 私有模块。
- Archive 只能做索引、校验和保存说明；禁止被 Product/Lab 当作运行时代码导入。
- 根目录只维护导航、Source of Truth、贡献/安全策略和组合 CI；不得新增产品实现或实验实现。

## 结构性重组纪律

结构性 PR 必须保持：

- retrieval query normalization、候选语义、score/rank/threshold/budget、证据顺序；
- scope、validity、revocation、lifecycle、权限、trace、公开 schema 和错误语义；
- PostgreSQL migration、CAS、幂等、RLS、outbox 和 fail-closed 行为；
- benchmark 数据、实验标签、历史结论和 formal holdout 的原样性。

禁止在结构 PR 中调参、改 Prompt、调 ranking/threshold/budget、重写 migration、改变 Evidence
或 Canonical 语义、消费 formal holdout、把实验结果升级为产品结论。若发现行为差异，登记
`MiLAi-Product/docs/TECH_DEBT.md`，另开行为 Goal/PR。

## Legacy 操作

根目录 `architecture/ contracts/ docs/ evals/ examples/ integrations/ research/ runtime/ scripts/ tests/`
和根级 Goal/报告现在是 read-only input。删除或退出活动面前必须完成：

```text
100% inventory coverage
→ every DIVERGED path has a recorded decision
→ relevant tests/package/boundary checks
→ clean annotated rollback tag
→ retire exact legacy paths
→ final report and remote verification
```

不得删除用户未授权范围外的 sibling checkout、第三方项目、`.venv`、uv cache、模型或运行产物。
不要把本仓库外的同名目录加入 Git。

## 安全与数据

- 不提交真实 token、密码、私钥、`.env`、用户私密正文、模型文件、数据库 dump 或运行日志。
- `.env.example` 可以提交；本地 `.venv`、`venv`、`.uv-cache`、`var`、`logs`、`artifacts` 和
  wheel/archive 输出必须保持 ignored。
- 不为了让测试通过而放宽 scope、认证、权限、删除传播、CAS、幂等或错误处理。

## 验证和交付

先运行受影响 bundle 的最窄测试，再按风险扩大到 package、边界、composition 和 PostgreSQL
门禁。交付说明必须包含：改动路径、是否改变 Schema/API/权限/Canonical 行为、已运行和未运行的
测试、依赖边界结果、回滚 tag/commit、未解决 debt，以及远端 commit 是否核对。

当前产品状态仍为 Runtime `0.1.x CANDIDATE`、Schema `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`；
不要把“代码存在”或“局部测试通过”表述成 production ready。
