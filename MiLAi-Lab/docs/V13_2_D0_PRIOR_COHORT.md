# v13.2 D0：旧生命周期证据收口

2026-10-01。状态：已完成限定的Root开发诊断；独立语义评分未完成。

以核实的远端main `95bf708bfd8aac9f7855485166e3bf739928b949` 建立独立v13.2工作树。原计划589行完整阅读，SHA256 `84c89a3e8dbb1f23ad4478e8a809f264c76c430b537b0ea1501671230681a79a`。旧生命周期执行身份仍是 `eaff074`，不是本次修复源码。

[机器证据表](../data/manifests/v13-2-d0-prior-cohort-results.json)重新读取139份原回执和139份原HTTP trace，并逐文件与旧冻结哈希比较；101条原回答保留在ignored审查包。60条原计划轨迹仍为45尝试、30完整消息、15中断、15未运行。逐条阅读全部30完整轨迹的公开目标、回答与原user/tool来源，并核对原世界/动作审计及记忆提交。原数据库、历史账本、原评分和终态均未改写。

补充维度是事后诊断；原协议的Root世界/journal/source/record/proposal审查边界保留。没有独立Judge，也没有把Root复核称为盲审或完整准确率。`NO_DEFINITE_CONTRADICTION_IDENTIFIED`只表示本次未确认明显矛盾，不能当完整任务成功。

## 已确认的链路问题

- 保留原四条反例；另确认StrongRawRAG native／unknown-none最后回答虽正确列出后续complete_label未知，结尾仍将UNKNOWN错误归给初始reserve_and_label。初始真实回执是已保存的reserved_label_failed。
- Field matched／partial中，原卡UPDATE先因缺fields被拒，随后因为receipt_already_consumed拒绝；新CREATE形成四张分开观察卡。完整最终历史解释可以正确，但并没有实现原卡增量修订。
- Field matched／clean最终回答正确，但第二张卡notes把前一个get_reservation源的found说成label_created。有限fields相符不代表notes也被验证。
- Field native／unknown-effect最终正确区分当前created和旧not_created、原complete_label未知；其旧卡UPDATE持续field_conflict/缺fields拒绝，旧卡未修订。
- B2/B6显式Host manage_memory多次遭native_method_has_no_requested_operation拒绝。其原文/回执后端自动保存真实观察另有证据；不能把语义卡namespace为空解释成完全没有记忆。新公平合同需要准确呈现可用操作。
- provider正常stop的未完历史说明、provider长度截断、额度耗尽和Qdrant已关闭错误分开。旧15中断原因为10额度耗尽、2截断、3证据关闭错误，未补答。

## 真实调用费用

| 请求用途 | 请求数 | 已知tokens |
| --- | ---: | ---: |
| Host JSON-action | 414 | 2,027,513 |
| 边界writer与续接 | 126 | 619,934 |
| 非JSON-action（Mem0原生抽取） | 3 | 27,852 |
| embedding | 295 | 83,740 |

543 generation／2,675,299 generation tokens与295 embedding／83,740 tokens逐请求对上原cohort。160次紧接失败记忆工具的下一请求共951,349 tokens，是上述请求的重叠子集；不能另加到账单，也不能把它全部解释成可消除浪费。

Field matched的58 writer调用／330,219 tokens占其559,647 tokens的大部分，其Host另48调用／229,428 tokens；projection-off的68 writer调用／289,715 tokens，Host另54／246,246。旧writer每工具边界形成与Host重复写入的请求路径是真实成本；新方法仍需同预算对照才能把节省归给机制。

## 原60条状态与首个可见断点

下表的错误是最早实际记忆拒绝或首个终止错误，不等于它一定因果导致整个轨迹失败。完整逐尝试序号、call ID、source/hash、回执与费用可追到机器表。

| 方法 | 原故事 | 原终态 | 首个记忆拒绝／终止 | 最终历史说明诊断 | generation tokens |
| --- | --- | --- | --- | --- | ---: |
| B2-matched | p5-clean | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 45,653 |
| B2-matched | p5-partial-w2 | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 46,777 |
| B2-matched | p5-known-no-effect | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 42,934 |
| B2-matched | p5-unknown-happened | COMPLETE | native_method_has_no_requested_operation | WRONG_ORIGINAL_CALL_IDENTITY | 55,151 |
| B2-matched | p5-unknown-none | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 53,266 |
| B2-matched | p5-update-w3 | INCOMPLETE | native_method_has_no_requested_operation；VLLM_CHAT_TRUNCATED | 未完成/未运行，不猜语义分 | 44,598 |
| B6-matched | p5-clean | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 44,593 |
| B6-matched | p5-partial-w2 | INCOMPLETE | native_method_has_no_requested_operation；PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED | 未完成/未运行，不猜语义分 | 135,082 |
| B6-matched | p5-known-no-effect | COMPLETE | native_method_has_no_requested_operation | UNSUPPORTED_UNKNOWN | 63,616 |
| B6-matched | p5-unknown-happened | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 78,311 |
| B6-matched | p5-unknown-none | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 75,144 |
| B6-matched | p5-update-w3 | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 59,196 |
| mem0_trace_equal-matched | p5-clean | INCOMPLETE | native_method_has_no_requested_operation；V13_P5_EVIDENCE_CAPTURE_FAILED:{'type': 'RuntimeError', 'error': 'QdrantLocal instance is closed. Please create a new instance.'} | 未完成/未运行，不猜语义分 | 14,513 |
| mem0_trace_equal-matched | p5-partial-w2 | INCOMPLETE | native_method_has_no_requested_operation；V13_P5_EVIDENCE_CAPTURE_FAILED:{'type': 'RuntimeError', 'error': 'QdrantLocal instance is closed. Please create a new instance.'} | 未完成/未运行，不猜语义分 | 23,543 |
| mem0_trace_equal-matched | p5-known-no-effect | INCOMPLETE | native_method_has_no_requested_operation；V13_P5_EVIDENCE_CAPTURE_FAILED:{'type': 'RuntimeError', 'error': 'QdrantLocal instance is closed. Please create a new instance.'} | 未完成/未运行，不猜语义分 | 17,956 |
| mem0_trace_equal-matched | p5-unknown-happened | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| mem0_trace_equal-matched | p5-unknown-none | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| mem0_trace_equal-matched | p5-update-w3 | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| field_grounded-matched | p5-clean | COMPLETE | receipt_fields_required | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 77,500 |
| field_grounded-matched | p5-partial-w2 | COMPLETE | receipt_fields_required | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 114,647 |
| field_grounded-matched | p5-known-no-effect | INCOMPLETE | VLLM_CHAT_TRUNCATED | 未完成/未运行，不猜语义分 | 56,495 |
| field_grounded-matched | p5-unknown-happened | INCOMPLETE | receipt_body_invalid_json；PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED | 未完成/未运行，不猜语义分 | 84,030 |
| field_grounded-matched | p5-unknown-none | INCOMPLETE | receipt_fields_required；PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED | 未完成/未运行，不猜语义分 | 110,862 |
| field_grounded-matched | p5-update-w3 | INCOMPLETE | object_ref_not_found_or_not_owned；PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED | 未完成/未运行，不猜语义分 | 116,113 |
| B2-native | p5-clean | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 25,077 |
| B2-native | p5-partial-w2 | COMPLETE | native_method_has_no_requested_operation | WRONG_ORIGINAL_CALL_IDENTITY | 35,609 |
| B2-native | p5-known-no-effect | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 33,366 |
| B2-native | p5-unknown-happened | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 35,570 |
| B2-native | p5-unknown-none | COMPLETE | native_method_has_no_requested_operation | WRONG_ORIGINAL_CALL_IDENTITY | 45,194 |
| B2-native | p5-update-w3 | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 32,693 |
| B6-native | p5-clean | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 30,223 |
| B6-native | p5-partial-w2 | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 32,898 |
| B6-native | p5-known-no-effect | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 33,158 |
| B6-native | p5-unknown-happened | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 45,114 |
| B6-native | p5-unknown-none | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 44,533 |
| B6-native | p5-update-w3 | COMPLETE | native_method_has_no_requested_operation | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 32,584 |
| mem0_trace_equal-native | p5-clean | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| mem0_trace_equal-native | p5-partial-w2 | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| mem0_trace_equal-native | p5-known-no-effect | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| mem0_trace_equal-native | p5-unknown-happened | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| mem0_trace_equal-native | p5-unknown-none | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| mem0_trace_equal-native | p5-update-w3 | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| field_grounded-native | p5-clean | COMPLETE | field_conflict:status | INCOMPLETE_HISTORY_EXPLANATION | 48,170 |
| field_grounded-native | p5-partial-w2 | COMPLETE | receipt_body_conflict:status | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 41,062 |
| field_grounded-native | p5-known-no-effect | INCOMPLETE | field_conflict:status；PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED | 未完成/未运行，不猜语义分 | 86,117 |
| field_grounded-native | p5-unknown-happened | COMPLETE | field_conflict:status | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 45,532 |
| field_grounded-native | p5-unknown-none | INCOMPLETE | field_conflict:status；PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED | 未完成/未运行，不猜语义分 | 83,572 |
| field_grounded-native | p5-update-w3 | COMPLETE | receipt_fields_required | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 48,886 |
| field_grounded-projection-off | p5-clean | COMPLETE | receipt_fields_required | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 89,833 |
| field_grounded-projection-off | p5-partial-w2 | INCOMPLETE | receipt_fields_required；PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED | 未完成/未运行，不猜语义分 | 81,828 |
| field_grounded-projection-off | p5-known-no-effect | INCOMPLETE | receipt_fields_required；PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED | 未完成/未运行，不猜语义分 | 77,844 |
| field_grounded-projection-off | p5-unknown-happened | INCOMPLETE | receipt_fields_required；PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED | 未完成/未运行，不猜语义分 | 82,459 |
| field_grounded-projection-off | p5-unknown-none | INCOMPLETE | receipt_fields_required；PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED | 未完成/未运行，不猜语义分 | 80,261 |
| field_grounded-projection-off | p5-update-w3 | COMPLETE | receipt_fields_required | NO_DEFINITE_CONTRADICTION_IDENTIFIED | 123,736 |
| mem0_trace_equal-manual-update | p5-clean | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| mem0_trace_equal-manual-update | p5-partial-w2 | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| mem0_trace_equal-manual-update | p5-known-no-effect | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| mem0_trace_equal-manual-update | p5-unknown-happened | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| mem0_trace_equal-manual-update | p5-unknown-none | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |
| mem0_trace_equal-manual-update | p5-update-w3 | NOT_RUN | — | 未完成/未运行，不猜语义分 | 0 |

## 代码与预算身份

[入口冻结](../data/manifests/v13-2-entry-freeze.json)记录旧执行到main的20个source/config差异，包括文稿工作流、恢复、关闭顺序与observed_events_v1载体。不能把main修复状态写回旧eaff074执行。旧每消息12次生成跨重启累计；v13.2后续质量24和共同12将另冻结、另报。

v13.2入口原连续账本实际为7,946次generation／20,341,038 charged generation tokens（20,310,651已知、30,387保守未知费用）／717,188 embedding tokens。generation unknown usage为1，embedding为0。账本包括随后旧v13.1文稿运行，不能使用规划中的7,461快照当当前余额。本次D0新增实验请求0，未估算美元或GPU小时。

## 审查与复现

已输出方法显式标签移除、固定hash顺序的30完整轨迹审查包和独立private映射，真实源、原回答和动作保留。包可供将来的独立审查者使用，但当前状态仍PREPARED_NOT_INDEPENDENTLY_SCORED；运行行为可能透露方法，不能声称完全遮盲。

```bash
python3 tools/audit_v13_2_prior_cohort.py \
  --coverage data/manifests/v13-1-p5-comparison-old208-coverage-results.json \
  --notes data/manifests/v13-2-d0-review-notes.json \
  --output data/manifests/v13-2-d0-prior-cohort-results.json \
  --private-dir artifacts/v13-2-d0/audit
```

该命令只读旧证据并生成新的审计产物，缺少原private路径时不能假装公开manifest已证明全部原始轨迹。脚本ruff检查通过；没有运行模型、全套测试或build。完整v13.2 Goal保持ACTIVE，Product NO_GO。
