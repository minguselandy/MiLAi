---
document_id: MILA-EVENT-RECONCILIATION-PHASE-C3-COMPLETION
version: "1.0"
status: PASS_MINIMAL_STATE_DELTA_VALIDATE_MERGE
date: 2026-09-05
milestone: PHASE_C3_MINIMAL_STATE_DELTA
database_write: NONE
model_call: NONE
public_mcp_schema_change: NONE
---

# MiLA Event Reconciliation Phase C3 完成报告

## 1. 结论

C3 已交付纯 Host-side StateDelta validation/merge primitive：

```text
previous Working State payload
  + untrusted StateDelta
  + exact base head
  + eligible Event identities
  -> validated full replacement payload
```

终态：

```text
PASS_MINIMAL_STATE_DELTA_VALIDATE_MERGE
```

这不证明 Codex 会生成正确 Delta，也没有写数据库；它只证明机械边界和后续 CAS handoff shape。

## 2. 已实现合同

- 完整 envelope：`base_state_id/base_version/no_material_change/changes`；
- create base 只能是 `null/0`，existing base 只能是 non-empty ID/version>0；
- raw Delta base 必须精确匹配 Host expected base；
- missing semantic field = KEEP；
- 一个字段最多一个 `REPLACE` 或 `CLEAR`；
- `REPLACE` 使用直接 JSON full-field value；
- `CLEAR` 删除整个 semantic field，不能携带非空 replacement；
- 每个变化必须引用唯一、非空、属于 frozen window 的 exact Event ID；
- Event ref 校验只声明 reference validity，不声称 semantic grounding；
- authority/binding/scope/version/basis 与 arbitrary JSON Patch 不在可改字段集合；
- 未涉及的已有字段和 Host extension 深拷贝保留，输入不原地修改；
- 相同 replacement 或清除不存在字段返回 `NO_EFFECTIVE_CHANGE`，避免无意义 StateVersion；
- merge result 携带 validated base State ID/version，供 C4 构造 exact CAS；
- 所有 contract error 提供 `code/problem/fix`。

## 3. 测试

```text
hooks full suite          34 passed
focused StateDelta       17 passed
Ruff                      PASS
mypy                      PASS
hooks build               PASS
```

覆盖内容包括：replacement、clear、keep、未知字段保留、输入不可变、no-material、非法 authority
字段、重复字段、非法操作、空/重复/窗口外 Event refs、NaN、envelope 缺失、base mismatch、非法 create/
update base 组合、bool version，以及两种 effective no-op。

## 4. Failure reflection

初版在两处会为 C4 埋下错误版本风险：

1. `base_state_id=null, version>0` 和 `id, version=0` 可通过，merge result 也没有携带 CAS base；
2. CLEAR 不存在字段或 REPLACE 相同值会被标成变化。

修复后 create/update shape 在 raw 与 Host expected 两侧都校验，result 自包含 exact CAS
precondition，并在 merge 后比较 effective payload。没有为此增加数据库、journal cursor、模型调用或
JSON Schema 服务。

## 5. Subagent review

```yaml
functional:
  decision: PASS
  required_fixes: []
architecture:
  decision: PASS
  required_fixes: []
generalization_and_simplicity:
  decision: PASS
  required_fixes: []
```

功能 reviewer 的两项 required finding 已修复并复核。没有人工 adjudication。

## 6. 下一步

C4 只增加受控 orchestration：Host 读取 exact Working State head 和 Event window，将 Codex-produced
Delta 交给 C3 validate/merge，再用 result 的 base ID/version 调用已有 Working State CAS。第一版
仍由显式 Host reconciliation 请求触发，不实现自动 dirty detector、session-end hook、epoch 或
retention-gap proof。

