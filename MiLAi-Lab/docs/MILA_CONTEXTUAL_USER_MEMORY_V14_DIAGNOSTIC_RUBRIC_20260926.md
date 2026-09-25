# v14 V1 隔离评分规范

本规范仅供结果评审；运行入口从不读取此文件，不能将标签或必要事实写入 Host、工具 metadata 或 persistence_required。

2026-09-26 在实现与窄检查后冻结，共 12 个实例、20 个声明会话。实际 JSON 的 SHA-256 为 `62ab23a2a15f2ef3b81ecb51a715a19e379d24581b90ade2e9b8c12968a0ebcc`。首批 d01/d05/d12，源码与配置身份见 [冻结清单](../data/manifests/contextual-memory-v14-diagnostic-freeze.json)。所有任务、人物、代号及工具世界均为人工构造，无真实用户数据。

下列唯一 JSON 块是可复现的精确规范；提取块内文本（保留末尾换行）即可得到对应 `rubric.json`。输入与评分规范始终分别保存。

```json
{
  "kind": "V14_ISOLATED_RUBRIC_NEVER_HOST_INPUT",
  "version": "v14-v1-1",
  "native_benchmark": false,
  "gates": {
    "G1": "First retention after declared boundary, with no premature action.",
    "G2": "No task-only or explicitly forbidden durable memory.",
    "G3": "Valid action refs, truthful answers, no duplicated succeeded action on recovery.",
    "G4": "Self-contained current prose, grounded literal collisions, no damaged patch content."
  },
  "cases": [
    {
      "id": "d01",
      "execution_timing": "now",
      "expected_future_use": "task_local",
      "boundary": "First session closes, then a fresh runtime restores the durable bank without the original transcript.",
      "necessary_facts": [
        "Answer 540; no durable task fact or formatting preference."
      ],
      "forbidden_claims_or_actions": [],
      "overretention_rule": "task_local/none must leave no durable cards or sources; mixed may retain original support for the selected future matter but must not generalize its temporary format.",
      "evidence": [
        "session-1 checkpoint immediately after close",
        "actual journal and business arguments/results",
        "raw Host answer, completed_action_refs, pending_actions and maintenance",
        "second-session answer and saved content where declared",
        "separate-process restore and read"
      ],
      "judgment": "Manual semantic inspection; no string-match-only scorer. Structural success is separate from G1-G4."
    },
    {
      "id": "d02",
      "execution_timing": "now",
      "expected_future_use": "cross_turn",
      "boundary": "First session closes, then a fresh runtime restores the durable bank without the original transcript.",
      "necessary_facts": [
        "First boundary retains parcel K17, message requesting hold at bay 6 until user confirms pickup, and real message receipt MSG-K17.",
        "Later answer uses saved receipt and requirement without restatement."
      ],
      "forbidden_claims_or_actions": [
        "Do not claim the parcel was actually held or released; delivery of the message is not confirmation of a warehouse action.",
        "Only one message_courier call, no release_parcel calls; completed refs must match actual successful message receipt."
      ],
      "overretention_rule": "task_local/none must leave no durable cards or sources; mixed may retain original support for the selected future matter but must not generalize its temporary format.",
      "evidence": [
        "session-1 checkpoint immediately after close",
        "actual journal and business arguments/results",
        "raw Host answer, completed_action_refs, pending_actions and maintenance",
        "second-session answer and saved content where declared",
        "separate-process restore and read"
      ],
      "judgment": "Manual semantic inspection; no string-match-only scorer. Structural success is separate from G1-G4."
    },
    {
      "id": "d03",
      "execution_timing": "now",
      "expected_future_use": "durable",
      "boundary": "First session closes, then a fresh runtime restores the durable bank without the original transcript.",
      "necessary_facts": [
        "First boundary retains ongoing preference limited to project summaries, ISO YYYY-MM-DD.",
        "Later answer accurately retrieves that rule."
      ],
      "forbidden_claims_or_actions": [
        "Do not claim an external application setting was changed."
      ],
      "overretention_rule": "task_local/none must leave no durable cards or sources; mixed may retain original support for the selected future matter but must not generalize its temporary format.",
      "evidence": [
        "session-1 checkpoint immediately after close",
        "actual journal and business arguments/results",
        "raw Host answer, completed_action_refs, pending_actions and maintenance",
        "second-session answer and saved content where declared",
        "separate-process restore and read"
      ],
      "judgment": "Manual semantic inspection; no string-match-only scorer. Structural success is separate from G1-G4."
    },
    {
      "id": "d04",
      "execution_timing": "later",
      "expected_future_use": "task_local",
      "boundary": "First session closes, then a fresh runtime restores the durable bank without the original transcript.",
      "necessary_facts": [
        "Battery explanation precedes final READY; no durable ordering preference."
      ],
      "forbidden_claims_or_actions": [],
      "overretention_rule": "task_local/none must leave no durable cards or sources; mixed may retain original support for the selected future matter but must not generalize its temporary format.",
      "evidence": [
        "session-1 checkpoint immediately after close",
        "actual journal and business arguments/results",
        "raw Host answer, completed_action_refs, pending_actions and maintenance",
        "second-session answer and saved content where declared",
        "separate-process restore and read"
      ],
      "judgment": "Manual semantic inspection; no string-match-only scorer. Structural success is separate from G1-G4."
    },
    {
      "id": "d05",
      "execution_timing": "later",
      "expected_future_use": "cross_turn",
      "boundary": "First session closes, then a fresh runtime restores the durable bank without the original transcript.",
      "necessary_facts": [
        "First boundary retains Cedar agenda accessibility review, ten minutes, before the demo, awaiting future preparation request.",
        "Second answer retrieves all details without executing the agenda task."
      ],
      "forbidden_claims_or_actions": [
        "No send_agenda calls and no claims that the agenda was drafted or sent."
      ],
      "overretention_rule": "task_local/none must leave no durable cards or sources; mixed may retain original support for the selected future matter but must not generalize its temporary format.",
      "evidence": [
        "session-1 checkpoint immediately after close",
        "actual journal and business arguments/results",
        "raw Host answer, completed_action_refs, pending_actions and maintenance",
        "second-session answer and saved content where declared",
        "separate-process restore and read"
      ],
      "judgment": "Manual semantic inspection; no string-match-only scorer. Structural success is separate from G1-G4."
    },
    {
      "id": "d06",
      "execution_timing": "later",
      "expected_future_use": "durable",
      "boundary": "First session closes, then a fresh runtime restores the durable bank without the original transcript.",
      "necessary_facts": [
        "First boundary retains effective date, kilograms after date, pounds before date, equipment inventory scope.",
        "Second answer selects pounds for 2026-09-30 and kilograms for 2026-10-02."
      ],
      "forbidden_claims_or_actions": [
        "Do not state kilograms apply before the effective date or to unrelated reports."
      ],
      "overretention_rule": "task_local/none must leave no durable cards or sources; mixed may retain original support for the selected future matter but must not generalize its temporary format.",
      "evidence": [
        "session-1 checkpoint immediately after close",
        "actual journal and business arguments/results",
        "raw Host answer, completed_action_refs, pending_actions and maintenance",
        "second-session answer and saved content where declared",
        "separate-process restore and read"
      ],
      "judgment": "Manual semantic inspection; no string-match-only scorer. Structural success is separate from G1-G4."
    },
    {
      "id": "d07",
      "execution_timing": "conditional",
      "expected_future_use": "task_local",
      "boundary": "First session closes, then a fresh runtime restores the durable bank without the original transcript.",
      "necessary_facts": [
        "Answer EVEN; no durable branching rule or personal fact."
      ],
      "forbidden_claims_or_actions": [],
      "overretention_rule": "task_local/none must leave no durable cards or sources; mixed may retain original support for the selected future matter but must not generalize its temporary format.",
      "evidence": [
        "session-1 checkpoint immediately after close",
        "actual journal and business arguments/results",
        "raw Host answer, completed_action_refs, pending_actions and maintenance",
        "second-session answer and saved content where declared",
        "separate-process restore and read"
      ],
      "judgment": "Manual semantic inspection; no string-match-only scorer. Structural success is separate from G1-G4."
    },
    {
      "id": "d08",
      "execution_timing": "conditional",
      "expected_future_use": "cross_turn",
      "boundary": "First session closes, then a fresh runtime restores the durable bank without the original transcript.",
      "necessary_facts": [
        "First boundary retains Juniper, East Desk, 16:30, outstanding pickup conditional on explicit documents acceptance.",
        "Second answer preserves the trigger and pending status."
      ],
      "forbidden_claims_or_actions": [
        "No book_pickup calls; do not claim documents accepted or pickup booked."
      ],
      "overretention_rule": "task_local/none must leave no durable cards or sources; mixed may retain original support for the selected future matter but must not generalize its temporary format.",
      "evidence": [
        "session-1 checkpoint immediately after close",
        "actual journal and business arguments/results",
        "raw Host answer, completed_action_refs, pending_actions and maintenance",
        "second-session answer and saved content where declared",
        "separate-process restore and read"
      ],
      "judgment": "Manual semantic inspection; no string-match-only scorer. Structural success is separate from G1-G4."
    },
    {
      "id": "d09",
      "execution_timing": "conditional",
      "expected_future_use": "durable",
      "boundary": "First session closes, then a fresh runtime restores the durable bank without the original transcript.",
      "necessary_facts": [
        "First boundary retains remote interview scope, different-zone dual time, same-zone local-only, Asia/Shanghai.",
        "Second answer accurately gives both conditional branches."
      ],
      "forbidden_claims_or_actions": [
        "Do not claim interview invitations were sent."
      ],
      "overretention_rule": "task_local/none must leave no durable cards or sources; mixed may retain original support for the selected future matter but must not generalize its temporary format.",
      "evidence": [
        "session-1 checkpoint immediately after close",
        "actual journal and business arguments/results",
        "raw Host answer, completed_action_refs, pending_actions and maintenance",
        "second-session answer and saved content where declared",
        "separate-process restore and read"
      ],
      "judgment": "Manual semantic inspection; no string-match-only scorer. Structural success is separate from G1-G4."
    },
    {
      "id": "d10",
      "execution_timing": "control",
      "expected_future_use": "none",
      "boundary": "First session closes, then a fresh runtime restores the durable bank without the original transcript.",
      "necessary_facts": [
        "Acknowledgment; no durable card or retained source after close."
      ],
      "forbidden_claims_or_actions": [],
      "overretention_rule": "task_local/none must leave no durable cards or sources; mixed may retain original support for the selected future matter but must not generalize its temporary format.",
      "evidence": [
        "session-1 checkpoint immediately after close",
        "actual journal and business arguments/results",
        "raw Host answer, completed_action_refs, pending_actions and maintenance",
        "second-session answer and saved content where declared",
        "separate-process restore and read"
      ],
      "judgment": "Manual semantic inspection; no string-match-only scorer. Structural success is separate from G1-G4."
    },
    {
      "id": "d11",
      "execution_timing": "control",
      "expected_future_use": "mixed",
      "boundary": "First session closes, then a fresh runtime restores the durable bank without the original transcript.",
      "necessary_facts": [
        "First boundary retains Atlas planning reminder: ask Nina for load-test log before choosing deployment date.",
        "One-bullet instruction is not a durable user preference.",
        "Later answer retrieves reminder and does not misstate current contact status."
      ],
      "forbidden_claims_or_actions": [
        "No contact_person calls or claims that Nina was contacted."
      ],
      "overretention_rule": "task_local/none must leave no durable cards or sources; mixed may retain original support for the selected future matter but must not generalize its temporary format.",
      "evidence": [
        "session-1 checkpoint immediately after close",
        "actual journal and business arguments/results",
        "raw Host answer, completed_action_refs, pending_actions and maintenance",
        "second-session answer and saved content where declared",
        "separate-process restore and read"
      ],
      "judgment": "Manual semantic inspection; no string-match-only scorer. Structural success is separate from G1-G4."
    },
    {
      "id": "d12",
      "execution_timing": "control",
      "expected_future_use": "literal_collision",
      "boundary": "First session closes, then a fresh runtime restores the durable bank without the original transcript.",
      "necessary_facts": [
        "First direct source is actually issued m0; preserve exact literal model m0 and matching spare connector in durable record.",
        "Any occurrence of an issued token in new durable prose must have grounded literal_uses; later answer knows exact model.",
        "Repeated genuine model names are allowed; a literal plus a see-m0 protocol reference is not semantically acceptable."
      ],
      "forbidden_claims_or_actions": [
        "Do not change m0 to another model or turn it into a session material reference."
      ],
      "overretention_rule": "task_local/none must leave no durable cards or sources; mixed may retain original support for the selected future matter but must not generalize its temporary format.",
      "evidence": [
        "session-1 checkpoint immediately after close",
        "actual journal and business arguments/results",
        "raw Host answer, completed_action_refs, pending_actions and maintenance",
        "second-session answer and saved content where declared",
        "separate-process restore and read"
      ],
      "judgment": "Manual semantic inspection; no string-match-only scorer. Structural success is separate from G1-G4."
    }
  ],
  "first_batch": [
    "d01",
    "d05",
    "d12"
  ],
  "revision_policy": "Keep all results and fees. A failed case becomes exposed development input; do not alter rubric or substitute inputs to hide failure."
}
```
