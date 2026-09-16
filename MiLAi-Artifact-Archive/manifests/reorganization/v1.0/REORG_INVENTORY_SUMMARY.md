# Reorganization Inventory Summary

- HEAD: `ba78b4bbba44573f1277f3484c19a4596c25e06a`
- Rollback tag: `pre-codebase-reorg-v1`
- Tracked records: **6423**
- Legacy records: **2206**
- Coverage: **100.0%** of the tracked repository surface
- UNKNOWN classifications: **0**
- DIVERGED records: **144**
- Unresolved DIVERGED decisions: **0**

## Legacy comparison status

| Status | Count |
| --- | ---: |
| `DIVERGED` | 144 |
| `IDENTICAL` | 2055 |
| `LEGACY_ONLY` | 7 |

## Classification

| Classification | Count |
| --- | ---: |
| `DOC_DUPLICATE` | 642 |
| `GOVERNANCE` | 25 |
| `HISTORICAL_ONLY` | 168 |
| `LAB` | 4158 |
| `PRODUCT` | 1430 |

## Gate interpretation

清单只覆盖 Git-tracked 文件；本地 `.venv`、uv cache、日志、运行状态、模型和生成性
大文件不属于提交面，并由根 `.gitignore` 与 Archive artifact catalog 管理。删除 legacy
前必须保持 `UNKNOWN=0`、每个 DIVERGED 都有 review decision，并重新运行 Product/Lab
边界、测试和 package gate。
