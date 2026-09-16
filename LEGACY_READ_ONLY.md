# Legacy Read-Only Policy

根目录历史混合源码正在退出活动面。自 `pre-codebase-reorg-v1` 起，以下路径只能用于
inventory、语义 diff、测试取证和恢复，不能新增功能、测试依赖或发布入口：

```text
architecture/ contracts/ docs/ evals/ examples/
integrations/ research/ runtime/ scripts/ tests/
```

根级 `DG-*`、`MF-*`、`MD-*`、`MVP-*`、`GOAL`、`REPORT`、`AUDIT` 和时间戳报告同样是历史输入。

规则：

1. 先查 `MiLAi-Product/`、`MiLAi-Lab/` 和 `MiLAi-Artifact-Archive/` 的对应权威内容。
2. 不因路径相似就认定两份源码等价；使用 inventory 的 SHA 和 divergence review。
3. 不把整个 legacy 目录复制、merge 或 re-export 到 Product/Lab。
4. legacy-only 内容若确有当前价值，记录 owner、最小 forward-port、测试和独立行为 PR。
5. 重组后 legacy 文件通过 Git tag/history 和 Archive manifest 恢复；Archive 不运行它们。

状态查询：

```bash
git show pre-codebase-reorg-v1:<legacy-path>
git log --all -- <legacy-path>
```

本文件不是 legacy 运行时兼容层，也不授权修改历史结论。
