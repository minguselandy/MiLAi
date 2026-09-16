# V02-16 Failure map 与描述性模式卡

状态：`FAILURE_MAP_RECORDED`。研究者非盲离线复核，无 Judge 模型。全部 36 阶段，两个根，
同根压力变体与冷阶段相关；不是 36 个独立任务。原始 label 评价不覆盖，复核另存
[reviewed-rows.json](/cra/memory/mx_memory/evidence/v0216/review-v1/reviewed-rows.json)，hash `c14eb2c304b0e2785131cfa938fe3697fdf0eb2dd2d59fcbc04fa3634a141685`。

## 逐阶段图谱

各行均为冷 Host、相同 V1 基线，5 个合法来源，自选笔记写入为 0。阶段 0 初始、1 无关更新、
2 有效当前版本更新；模拟 tick，不是真实长时间遗忘。low/high32/fallback8 分别为 0/32/8 条
其他对象记录，执行顺序为 0 → 32 → 8。来源字节数与目标偏移见完整行及执行报告。
成功行的全部必要支持已在最终请求呈现，解释复核正确。A=未发起必要取得；R=读取/检索
未取得目标支持；这不是“充分反证已呈现而仍用错”。失败为不当全局缺失断言，不能当合理澄清。

| 条件 / 根 / 组 / 阶段 | 结果 / 最早层 | 首个明确错误事件 | 请求 / raw | 读 / 搜索 | 秒 | 原始动作 |
| --- | --- | --- | --- | --- | --- | --- |
| low/trace/NOTES/0 | 成功 | — | 2 / 6,635 | 5 / 0 | 7.03 | [actions](/cra/memory/mx_memory/evidence/v0216/low-v1-20260910/runs/trace/NOTES/phase-0/actions.jsonl) |
| low/trace/REMINDER/0 | 成功 | — | 2 / 6,726 | 5 / 0 | 6.26 | [actions](/cra/memory/mx_memory/evidence/v0216/low-v1-20260910/runs/trace/REMINDER/phase-0/actions.jsonl) |
| low/trace/NOTES/1 | 成功 | — | 2 / 6,683 | 5 / 0 | 6.36 | [actions](/cra/memory/mx_memory/evidence/v0216/low-v1-20260910/runs/trace/NOTES/phase-1/actions.jsonl) |
| low/trace/REMINDER/1 | 成功 | — | 2 / 6,760 | 5 / 0 | 6.43 | [actions](/cra/memory/mx_memory/evidence/v0216/low-v1-20260910/runs/trace/REMINDER/phase-1/actions.jsonl) |
| low/trace/NOTES/2 | 成功 | — | 2 / 6,714 | 5 / 0 | 6.35 | [actions](/cra/memory/mx_memory/evidence/v0216/low-v1-20260910/runs/trace/NOTES/phase-2/actions.jsonl) |
| low/trace/REMINDER/2 | 成功 | — | 2 / 6,813 | 5 / 0 | 6.48 | [actions](/cra/memory/mx_memory/evidence/v0216/low-v1-20260910/runs/trace/REMINDER/phase-2/actions.jsonl) |
| low/placement/NOTES/0 | 成功 | — | 2 / 6,801 | 5 / 0 | 6.95 | [actions](/cra/memory/mx_memory/evidence/v0216/low-v1-20260910/runs/placement/NOTES/phase-0/actions.jsonl) |
| low/placement/REMINDER/0 | 成功 | — | 2 / 6,892 | 5 / 0 | 7.13 | [actions](/cra/memory/mx_memory/evidence/v0216/low-v1-20260910/runs/placement/REMINDER/phase-0/actions.jsonl) |
| low/placement/NOTES/1 | 成功 | — | 2 / 6,823 | 5 / 0 | 6.83 | [actions](/cra/memory/mx_memory/evidence/v0216/low-v1-20260910/runs/placement/NOTES/phase-1/actions.jsonl) |
| low/placement/REMINDER/1 | 成功 | — | 2 / 6,844 | 5 / 0 | 6.73 | [actions](/cra/memory/mx_memory/evidence/v0216/low-v1-20260910/runs/placement/REMINDER/phase-1/actions.jsonl) |
| low/placement/NOTES/2 | 成功 | — | 2 / 6,920 | 5 / 0 | 6.99 | [actions](/cra/memory/mx_memory/evidence/v0216/low-v1-20260910/runs/placement/NOTES/phase-2/actions.jsonl) |
| low/placement/REMINDER/2 | 成功 | — | 2 / 6,931 | 5 / 0 | 7.06 | [actions](/cra/memory/mx_memory/evidence/v0216/low-v1-20260910/runs/placement/REMINDER/phase-2/actions.jsonl) |
| high32/trace/NOTES/0 | 失败 / R | trace-p0-04 | 4 / 17,906 | 6 / 0 | 9.58 | [actions](/cra/memory/mx_memory/evidence/v0216/high32-v1-20260910/runs/trace/NOTES/phase-0/actions.jsonl) |
| high32/trace/REMINDER/0 | 失败 / R | trace-p0-05 | 8 / 59,680 | 9 / 1 | 20.68 | [actions](/cra/memory/mx_memory/evidence/v0216/high32-v1-20260910/runs/trace/REMINDER/phase-0/actions.jsonl) |
| high32/trace/NOTES/1 | 失败 / R | trace-p1-04 | 4 / 17,694 | 6 / 0 | 9.07 | [actions](/cra/memory/mx_memory/evidence/v0216/high32-v1-20260910/runs/trace/NOTES/phase-1/actions.jsonl) |
| high32/trace/REMINDER/1 | 失败 / R | trace-p1-04 | 4 / 17,847 | 6 / 0 | 9.07 | [actions](/cra/memory/mx_memory/evidence/v0216/high32-v1-20260910/runs/trace/REMINDER/phase-1/actions.jsonl) |
| high32/trace/NOTES/2 | 成功 | — | 7 / 46,367 | 8 / 1 | 16.18 | [actions](/cra/memory/mx_memory/evidence/v0216/high32-v1-20260910/runs/trace/NOTES/phase-2/actions.jsonl) |
| high32/trace/REMINDER/2 | 失败 / R | trace-p2-03 | 3 / 11,548 | 5 / 0 | 7.76 | [actions](/cra/memory/mx_memory/evidence/v0216/high32-v1-20260910/runs/trace/REMINDER/phase-2/actions.jsonl) |
| high32/placement/NOTES/0 | 失败 / R | placement-p0-03 | 4 / 19,129 | 6 / 0 | 12.81 | [actions](/cra/memory/mx_memory/evidence/v0216/high32-v1-20260910/runs/placement/NOTES/phase-0/actions.jsonl) |
| high32/placement/REMINDER/0 | 失败 / R | placement-p0-04 | 5 / 27,176 | 6 / 1 | 13.27 | [actions](/cra/memory/mx_memory/evidence/v0216/high32-v1-20260910/runs/placement/REMINDER/phase-0/actions.jsonl) |
| high32/placement/NOTES/1 | 成功 | — | 5 / 28,032 | 7 / 0 | 14.52 | [actions](/cra/memory/mx_memory/evidence/v0216/high32-v1-20260910/runs/placement/NOTES/phase-1/actions.jsonl) |
| high32/placement/REMINDER/1 | 成功 | — | 8 / 62,081 | 9 / 1 | 21.67 | [actions](/cra/memory/mx_memory/evidence/v0216/high32-v1-20260910/runs/placement/REMINDER/phase-1/actions.jsonl) |
| high32/placement/NOTES/2 | 成功 | — | 6 / 38,548 | 8 / 0 | 16.22 | [actions](/cra/memory/mx_memory/evidence/v0216/high32-v1-20260910/runs/placement/NOTES/phase-2/actions.jsonl) |
| high32/placement/REMINDER/2 | 成功 | — | 6 / 38,441 | 8 / 0 | 16.05 | [actions](/cra/memory/mx_memory/evidence/v0216/high32-v1-20260910/runs/placement/REMINDER/phase-2/actions.jsonl) |
| fallback8/trace/NOTES/0 | 失败 / A | trace-p0-02 | 2 / 6,100 | 1 / 0 | 6.15 | [actions](/cra/memory/mx_memory/evidence/v0216/fallback8-v1-20260910/runs/trace/NOTES/phase-0/actions.jsonl) |
| fallback8/trace/REMINDER/0 | 成功 | — | 2 / 7,379 | 5 / 0 | 7.15 | [actions](/cra/memory/mx_memory/evidence/v0216/fallback8-v1-20260910/runs/trace/REMINDER/phase-0/actions.jsonl) |
| fallback8/trace/NOTES/1 | 成功 | — | 3 / 11,687 | 5 / 0 | 8.75 | [actions](/cra/memory/mx_memory/evidence/v0216/fallback8-v1-20260910/runs/trace/NOTES/phase-1/actions.jsonl) |
| fallback8/trace/REMINDER/1 | 成功 | — | 2 / 7,284 | 5 / 0 | 6.38 | [actions](/cra/memory/mx_memory/evidence/v0216/fallback8-v1-20260910/runs/trace/REMINDER/phase-1/actions.jsonl) |
| fallback8/trace/NOTES/2 | 成功 | — | 2 / 7,261 | 5 / 0 | 6.36 | [actions](/cra/memory/mx_memory/evidence/v0216/fallback8-v1-20260910/runs/trace/NOTES/phase-2/actions.jsonl) |
| fallback8/trace/REMINDER/2 | 成功 | — | 3 / 11,783 | 5 / 0 | 8.13 | [actions](/cra/memory/mx_memory/evidence/v0216/fallback8-v1-20260910/runs/trace/REMINDER/phase-2/actions.jsonl) |
| fallback8/placement/NOTES/0 | 成功 | — | 2 / 7,579 | 5 / 0 | 7.69 | [actions](/cra/memory/mx_memory/evidence/v0216/fallback8-v1-20260910/runs/placement/NOTES/phase-0/actions.jsonl) |
| fallback8/placement/REMINDER/0 | 成功 | — | 3 / 12,295 | 5 / 0 | 11.42 | [actions](/cra/memory/mx_memory/evidence/v0216/fallback8-v1-20260910/runs/placement/REMINDER/phase-0/actions.jsonl) |
| fallback8/placement/NOTES/1 | 成功 | — | 3 / 12,111 | 5 / 0 | 9.10 | [actions](/cra/memory/mx_memory/evidence/v0216/fallback8-v1-20260910/runs/placement/NOTES/phase-1/actions.jsonl) |
| fallback8/placement/REMINDER/1 | 成功 | — | 2 / 7,778 | 5 / 0 | 7.73 | [actions](/cra/memory/mx_memory/evidence/v0216/fallback8-v1-20260910/runs/placement/REMINDER/phase-1/actions.jsonl) |
| fallback8/placement/NOTES/2 | 成功 | — | 3 / 12,311 | 5 / 0 | 9.29 | [actions](/cra/memory/mx_memory/evidence/v0216/fallback8-v1-20260910/runs/placement/NOTES/phase-2/actions.jsonl) |
| fallback8/placement/REMINDER/2 | 成功 | — | 3 / 12,394 | 5 / 0 | 9.00 | [actions](/cra/memory/mx_memory/evidence/v0216/fallback8-v1-20260910/runs/placement/REMINDER/phase-2/actions.jsonl) |

每个动作旁的同目录 `tool-results.jsonl`、`*-request.json`、`*-http.json`、
`provider-ledger.jsonl`、`transport-presentation.json` 可复核取得与实际发送；完整行包含
最终请求/HTTP 文件 hash。首次事件是可见错误的保守定位，不是推测内部判断形成时间。

## F1：局部读取被提升为全来源缺失

- 条件：32 条其他对象记录，目标位于来源尾部；trace 5 次、placement 2 次，共两个根。
- 现象：7 次失败均拿到 registry/规则，却没取得 source-03 的目标数据；6 次提前停止，
  1 次在重复读取后走到最终槽。没有伪造目标数值或执行业务动作。
- 首次事件逐行列于上表；最清楚的证据为 high32/trace/NOTES/0：只读 `[0,4096)`，
  工具仍返回 PARTIAL/next_cursor=4096，而最终声称 T81 不在任何来源。
- high32/trace/REMINDER/0 的事件 05/06 重读 offset 0，事件 08 声称读完 8428 字节，
  实际连续覆盖只到 6144。它确有最终槽压力，但更早的覆盖/读取错误已可见；只计 R 一次。
- 搜索的 `FULL_HISTORY_FITS` 路径返回整文件位置且 `source_coverage=PARTIAL`，不是
  已呈现全文；它未提供精确命中位置，是重要 representation 混杂。其他失败完全没有搜索。
- 反例：同压力仍有 5 次取得支持后正确，包括 trace NOTES p2、placement 四次后续阶段；
  较弱压力大幅改善但未全消失。因此不是统一阈值，也不是某个源永远不可读。
- 解释：普通取证与覆盖理解问题；目标支持未呈现，不标 PRESENTED_SUPPORT_USE_FAILURE。
  两种任务结构共享相同来源布局/工具，不能把两个根当作对不同生态的充分独立重复。

## F2：未读取关联来源就宣告缺失

- 仅 fallback8/trace/NOTES/0 一次。已读 T81 数值，却没请求 U32→T81 registry 和字典。
- 在第 02 次请求即交付证据不足，还剩 6 个槽。最早层 A，不是数值比较/记忆使用失误。
- 同条件 REMINDER p0 正确，是 `SIMPLE_REMEDY_AVAILABLE` 的探索性配对反例，尚非稳定效果。
  NOTES 本身在 p1/p2 也正确；来源重取、交付前覆盖检查值得后续诊断，不必提新 State。

## F3：正确行为可保留，但成本增加

- high32 的正确完成分别需要 5–8 次请求，低压均 2 次；全部高压 raw 是低压的约 4.71 倍。
- 高压既有直接跳转尾部，也有顺序续读；调用过搜索不等于搜索精确命中。提醒组高压更贵且
  正确数更少，弱压则少一次失败；不能宣称提醒有稳定优势或劣势。
- 重读未变版本只作 POST_HOC 成本指标，不能自动叫无用劳动。P1 长期中断、P2 交错、
  P5 未决分支、P6 笔记累积未测；错误重开、遗失未决分支和旧前提保持均 N/A。

## 记忆因果边界与下一步

36 次模型都选择空 note，所有冷读回 State ABSENT。机械 CAS 写入/新进程读回通过，不等于
模型做过语义记忆使用。P4 更新有 12 个阶段，其中 11 次新数据呈现且答对，1 次未取到新数据；
没有“保存的旧判断 + 已呈现的同对象反证 + 后续仍依赖旧判断”的可裁定链。
POST_UPDATE_OLD_PREMISE_PERSISTENCE 不成立；memory-induced 更未测试。

本批保留简单方案，停止机制开发。若后续获得新范围，应优先单独诊断普通搜索范围表示与
完整性判断，或设计自然需要自选笔记的未决任务；固定当前失败作反例，不把此次工程/取得
问题转包装成新记忆理论。详细成本与六项结论见 [执行报告](MILA_V0216_EXECUTION_20260910.md)。
