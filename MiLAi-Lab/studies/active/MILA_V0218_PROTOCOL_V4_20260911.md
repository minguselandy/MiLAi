# V0218：已结算动作编码错误的通用反馈修复

状态：COMMON_HOST_V4 / 全臂重新冻结基线，非 Memory 候选。
这次变更不修改公开 task、world、checker、system、动作 schema、Note 写作/展示政策或模型容量。

## 原始证据与诊断

旧 `e0-baseline-wave2-v1` 已完整执行并审计：14 episodes，7 PASS / 7 FAIL，
90 requests / 171324 raw，全部 settled。科研版本审批 A 与六 B 都 PASS、A NO_WRITE；
财务 A 与六 B 都 FAIL，A 自写 1 Note，4 个 B 旧 Note/当前事实双呈现。
财务这次实际写了记录、更新后各臂也实际算出 +0.5；主要缺 `basis_revision`，部分把它写成
`revision`，比较还缺 `direction`。不是此前 T4 的缺四条记录或始终坚持 −1.68，不回用旧失败解释。
这些必要字段在公开 task_A/task_B.record_fields 已明确，并非私有 checker 隐藏要求。
Note SHA `8dec4d6af476d1ccea970aeb8ef5da62dfaf7e5d6ac21fa0c9898c9a6fe8cde1`：
原始值/比较可核，注明来自 current；不把“已有来源记录”误断为完全正确的业务完成声明。

旧 `e0-baseline-wave3-v1` 第六个 episode 中止：
`journalist_task5-superseded-N0` 的请求 `journalist_task5-superseded-N0-04`。
HTTP 200，finish_reason=stop，prompt=3170、completion=1814、total=4984；
输出小于预留 4096，不是输出/context/计数截断。外层 JSON 合法，内部 `arguments_json`
在 JSON 字符串中缺少闭合部分，`json.loads` 返回 JSONDecodeError。
外层 strict JSON schema 只要求该字段是字符串，不保证字符串内部又是完整 JSON。
没有证据要求重启/调整 vLLM、改模型参数或增加 token cap。

原 Host 在实际 HTTP 请求/usage settled 后，直接 decode 动作；该异常越过了动作拒绝层，
导致整批停止。可观测的模型编码错误和未知提交/未知用量不应使用同一自动中止路径。
原错误可重复由 `verify_protocol_revision` 从已留原始 HTTP 文件解析，不靠描述猜测。

旧第三波保留 1 A + 5 B：6 个最终快照 FAIL，其中 1 个协议中止；
28 requests / 70024 raw，pending/violations=0。A 自写 Note=1，B 冷读=3，
仅 1 个 B 当前事实实际呈现，双呈现=0；故这些失败不能整体解释为 memory-use failure。
后续 8 个预定 episode 没有启动，第六原 lineage 没有在此批尝试。
其 API/PG 已停止，卷和所有失败请求保留；没有自动补跑。
旧 E0 三波总计 240 / 499308；加建设 210 / 384080，变更前总账 **450 / 883388**。

## 修复的确切边界

对已经结算、拿到字符串响应后的 action decode ValueError/TypeError：
保存原始请求/输出与 `invalid_action` 轨迹，返回带简短错误类型的 `ACTION_REJECTED`，
不执行任何世界或 Note 写入；下一步仍由模型在原分配的剩余生成次数/时间内决定。
不补闭合符、不猜数据、不提取内容绕过解析，不免费重发同一请求。
最后一次格式错误仍耗用交付预约，不另外增加生成。

HTTP/Provider/usage 未知、Note 提交未知、真正的禁止字段/数据越权保持原先停止/失败关闭路径。
本补丁只包围 decoder，不包围世界动作或记忆提交错误，不将危险写入降为可忽略异常。
N0/N1/N2 共用同一代码分支；只含原始反馈，不额外告诉任何源事实/当前答案/理想 Note。
新增 12 项三臂测试：外层残缺、内层残缺、未知 action、错误参数结构均不改变世界、不写 Note，
错误反馈进入下一请求，真实计数 3 次、最后只能 finish。它们是测试替身，不算实际模型恢复。
另 7 项修复准入/20-episode probe 计划检查拒绝伪重现、截断、未知用量、未清理或 checker 漂移。

## 后续运行与不得合并的范围

`configs/v0218-protocol-v4.json` 固定原失败请求、诊断与不变项；每个新 manifest 复制该决定，
记录原始 HTTP/result hash、旧/新 Host hash 与不再重收的旧成本。
新代码不绕过 T5 world/checker hash 或不可变 Product release pin 验证。

三波强基线均按原固定顺序重新运行 `e0-baseline-wave{1,2,3}-v2`，每波 14 episodes、
最多 224 请求；各波仍串行独立冻结。原 v1 已成功、语义失败和协议失败均保留，不只补失败臂，
不把 v1/v2 当同协议重复合并。T5 的来源/世界及实际公共持久链仍成立，Host 反馈变更另列。
真实运行的生成/Note/呈现分母只能由新批审计给出，单测不会补它们。

Helpful/Irrelevant/Unresolved probe 仍固定第 5/6 个原来源，两者同属 journalism。
`configs/v0218-e0-probes.json` 的预选 roots/variants 不变；只将前置批改为共同 v4 重基线，
新 probe 未开始前不能标已执行。它需要三个标准波终态、结算、审计、清理全部满足。
Probe 用各自一次新的自然 A、共 20 episodes/最多 320 请求，普通历史和既有业务记录各臂保留，
不因 Note 未写或内容不合用替换题目。

本变更是测试执行可靠性修复，不是候选机制收益；E1/E2 和 E5 仍需后续真实证据。
