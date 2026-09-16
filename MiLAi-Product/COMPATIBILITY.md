# Product Compatibility Contract

本文件定义重组期间必须保持的外部兼容面。结构整理不等于新版本发布，也不授权修改行为。

## 当前公开边界

- MCP 是主产品接口；`milai-codex-full-mcp` 和 `milai-agent-memory-mcp` 的工具名、输入/输出
  JSON 结构、认证失败语义和 scope 约束属于公开兼容面。
- Python client 的公开类、函数、错误模型和序列化格式属于内部 SDK 兼容面。
- Runtime HTTP API、migration 顺序、tenant/RLS、幂等 fingerprint、CAS、revocation fail-closed
  语义属于产品兼容面。
- OpenWorker relay/broker/Host adapter 是兼容路径；不得因文件拆分新增第二个 facade。

## 重组不变量

重组前后必须保持：

1. query normalization、candidate 语义、score/rank/threshold/budget、证据顺序与 readiness；
2. scope、validity、lifecycle、revocation、权限和 trace ownership；
3. 公开 schema、HTTP/MCP 方法、错误码及拒绝路径；
4. migration 原样、版本与 upgrade/downgrade 语义；
5. Product 不依赖 Lab、Archive 或根目录 legacy；clean install 不需要研究依赖。

## 验证证据

每次结构 PR 至少附：相关单元/合同测试、API/schema diff、golden 输入输出或 trace 比较、
package clean-install 结果和依赖边界扫描。发现真实行为差异时，停止结构 PR，登记
`MiLAi-Product/docs/TECH_DEBT.md`，另开行为修复 PR。

当前状态仍为：Runtime `0.1.x CANDIDATE`，Schema `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
