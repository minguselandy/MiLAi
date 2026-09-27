# LSA P2 R1：State 使用与独立参数错误

源码 `9a06615676e9bff2d5ea90664e967d7160617651`，
[冻结协议](../data/manifests/local-state-attention-p2-r1-protocol.json)。15 个 job 全部执行，
无重试、替换、截断或未知用量。只捕获第一条 Host answer/calls；业务工具执行和 Store
写入均为 0。下面不是端到端任务成功率，也不意味着 P1 已通过。

每个断点使用同一份真实 R2 bank；所有 Host 历史、工具合同及请求参数保留，只替换
工作视图。四个 all、四个 query、四个 focus 为方法诊断；另三个上界/反事实/来源探针
单列。运行前依据原请求与成功编辑回执重建 bank，逐项核对已交付的 State 正文。

## 12 个方法首响应

| 真实断点 | all | query top2 | 只读 focus |
| --- | --- | --- | --- |
| 改 B、当前问 A | 先请求 manage_memory，用了 State ID；未答 A | 正确回答 A | 正确回答 A；选 A+B |
| 组合执行 A+B | 两项参数全对 | 数量/地点对，但把地点和包装当对象 key | 数量/地点对，但把地点当对象 key |
| Noel 执行 | 数量 2，地点被缩写，key 单数化 | 先 search_memory，未到业务动作 | 只选污染卡；数量 1、地点缩写、key 单数化 |
| Mira 恢复 | get 用 reservation ID 作 item_key | 同左 | 同左 |

12 个方法 job 中，3 个直接给出正确的所需首响应、2 个要求进一步 memory 步骤、
7 个直接业务调用的参数错误。三臂各只有 1/4 直接正确；**不把中间工具步直接记成
最终任务失败**，也不执行后续步骤把分母或实验范围事后扩大。

## 三个单列诊断

1. 人工选择实际旧计划（未改写正文）：Noel 的数量 2、`south bay S-8`、包装正确。
   仍把对象 crates 改成 crate，并尝试用内部 State ID 调 manage_memory。
   这是 oracle selection 的使用能力探针，不是正常方法分数。
2. 相同旧计划的反事实值 7 / `north bay N-9`：Host 的数量和地点同步改变，仍有同样
   key/State-ID 问题。说明这次响应确实使用了 State 值；不证明通用路由或维护有效。
3. Mira 完整真实部分失败回执：get_reservation 正确使用实际对象 key，complete_label
   使用原 reservation ID，没有新建预留。证明在此请求上直接来源能消除键类型混淆；
   没有执行工具，因此不能宣称恢复完成。R2 创建时的单数 key 错误仍原样保留。

## 因果边界与首个断点

H1（获得支持）：实际维护视图污染/丢失字段；正确旧计划与原始回执提供了被污染视图
未稳定保留的可用信息。R2 在动作前写出“已尝试／失败”仍是第一个维护断点。
H2（获得局部支持）：选择影响交付；组合任务 focus 选中了原计划两卡，但 Host 仍填错
对象 key，不能把选择正确视为动作正确。
H3（保留）：Host/呈现合同有独立问题。正确计划仍被单数化，State 管理 ID 被用于另一
namespace 的 memory 工具；本诊断没有实际执行这种 memory 更新，不虚构其错误回执。

实际 wire 核查发现：background 的 query/focus 完全相同并输出相同；Noel 的 all/query
也完全相同，却分别产生业务调用与 memory search；Mira 三臂 wire 完全相同且都用错键。
因此单次输出差不能归因于 arm 标签或 embedding。temperature=0 不构成确定性保证，
本次不是方差试验，不根据有利单条轨迹提前停止。

决策：**继续一个来源身份保持的维护候选，P3 不启动**。同一 Sol 仅修控制输入和通用
状态迁移合同：保留用户/工具、actor/call 身份，区分意图、用户报告与已观察结果，保留
精确称呼/引用，U/A 分开；不同时改变 Host/业务工具或工作视图。不能借此声称已解决
独立 Host 参数错误。原两条完整 P1 轨迹重跑，并加一个“用户明确报告过去事件”的
反例，防止误修成只有工具才能提供事实。若同族失败继续，不再堆措辞。

另修程序机械删除依赖及内部 Store 计量，独立于语义合同；前者不作为模型事实支持，
后者不算效果改进。视图暴露内部 ID 的问题保留，若下一轮触发再单独冻结呈现修复，
不把多项变化混成 attention 因果效果。

## 成本与复现

| 角色 | 实际 HTTP | tokens | HTTP wall seconds |
| --- | ---: | ---: | ---: |
| task_host | 15 | 15547 | 9.518 |
| read_selector | 4 | 1973 | 2.052 |
| query_embedding | 4 | 768 | 0.277 |

生成合计 19 次 / 17520 tokens；全部失败和中间步骤保留，unknown=0。
连续账本 **922 generation calls / 1100126 generation tokens / 10394 embedding tokens**。
LSA 从启动至此共 59 次生成 / 57397 generation tokens / 777 embedding tokens，含 R1。

ignored 证据：`artifacts/local-state-attention/p2-r1/` 的 inputs/reconstruction、
execution-freeze、run_manifest、各 job、trace、wire-audit、前后账本。
输入 SHA256 `8b44e57fe3579f46dc89305f1729495e0c9df8e4aa5b13abfa9adb8e3141551a`。
实际 Host wire 除末尾工作视图外均与冻结输入相同，已独立核查。

```bash
.venv/bin/python tools/run_local_state_attention_read_probe.py prepare \
  --config artifacts/local-state-attention/p2-r1/config.json \
  --inputs artifacts/local-state-attention/p2-r1/inputs.json --run p2-r1 \
  --runtime-root artifacts/local-state-attention/p2-r1/run \
  --output artifacts/local-state-attention/p2-r1/run/prepared.json
```

随后按 inputs.jobs 顺序用相同共参执行 `run-job --prepared <prepared.json> --job <job_id>
--stage p2-r1`。已尝试 job 不覆盖；独立复现需新 run/root，并固定对应源码及原输入。
15 个首响应不能代替后续 P1 完整恢复、P3 匹配维护比较或 P5/P6 泛化。
