# Mem2Act全400结束后的原协议衔接与比较准备

目前只有固定400原实验在运行。本文核对了原1147份科学代码＋1份冻结观察器的完整文件字节、
既有SDK版本与三个真实已关闭首例的完整控制配置；**没有运行任何后续命令、primary、评分或归档**。
这不是全400Source审计通过或全800任务完成的证明。
[机器凭据和全部10条明确argv/环境](../data/manifests/a100-mem2act-closeout-handoff-20261109-v1.json)保留可复核执行入口。

## 先规范别名，再做全400审计

冻结协议serial_order的原文字面顺序是：

1. 当前fixed原owner实际终止，全部400最早原生首结果关闭，成本由owner支付，父子实际进程消失。
2. 原finalizer创建规范driver别名及closure，不改原case/driver，不重跑更好答案。
3. 对规范fixed别名执行冻结观察器v2的完整400Source/Store/Saver/角色/时钟/权限/应用/SDK/
   Host输入/返回NN审计，写入原协议指定的fixed-prefix-full400-audit-v1.json。
4. 只有fixed closure与全400审计均passed、400实际首次Host快照可重放、无实验模型worker时，
   才通过原owner显式启动primary400。
5. primary实际全400终止/支付/父子消失后，同样先规范别名，再完整400审计。
6. 两方法全量审计后，按原适配器评分并逐400payload审计；最后才允许原无损归档。

旧活动说明把审计与规范别名写反，已按原serial_order澄清。原冻结协议、Source、预算、模型、
checkpoint、初次结果和门禁没有改变。alias创建仅复制相同driver，但其顺序仍遵循原协议。
若出现意外失败/FAILED_WRAPPER，先保留Native return、等待真实owner退出支付，反思并处理
元数据或仅原NOT_RUN尾部；命令中的最终owner必须按实际continuation祖先重解，不能盲用旧owner重跑。

## 实际输入、环境与原门禁

检查了真实completed0、failed2和本次最后closed例的实际pre-first-Host捕获：公开完整query/schema、
原baseline context和tool catalog存在。primary的原replay_host_message会合并原memory_control与
仅policy/checkpoint两项override；完整max16384/head2048/预算/菜单相关字段保持，不采用旧LME的
observer覆盖错误。三个例子的核对不能替代最终所有400快照可重放门禁。

冻结v2观察器只有原已声明的三处receipt元数据变更：successful仍要求literal[]，failed缺少成功专用
字段时保存present=False/value=None未知，不伪造空或成功。使用**原科学protocol**作为CLI输入；
不是把observational protocol当运行protocol。SDK预加载顺序固定transformers4.52.3/tokenizers0.21.4，
再把HTTP依赖路径追加到后面，不用HTTP4.57遮蔽Native版本。

父owner沿实际既有HTTP Python3.11运行，primary子argv仍是原CUDAPY/attention wrapper/GPU2方案。
当前owner的--check-only也会在admission里读取原账本，因此固定400活着时**不运行该命令**。
本文只读固定协议、owner/driver、实际进程和快照；活动原账本没有被打开。

## 已准备的原始执行入口

以下是顺序与计量类型，完整shell quoting和环境保存在机器凭据。每条均标PREPARED_NOT_DISPATCHED，
没有自动后台队列；执行前必须核查实际上一阶段门禁。普通CPU命令用各自未占用GNU计时文件，
native owner不能套GNU计时，等实际退出后按whole−native＋已测parent一次计量。

| 顺序 | 明确动作 | 计量范围 |
|---:|---|---|
| 1 | fixed-earliest-first400-canonical-alias | ordinary GNU CPU timer; no native/model/residual rebill |
| 2 | fixed-full400-frozen-observer-v2-audit | ordinary GNU CPU timer; exact original audit output path |
| 3 | primary400-original-owner-explicit-launch | native owner UNWRAPPED; native plus whole residual/parent once at actual exit |
| 4 | primary-earliest-first400-canonical-alias | ordinary GNU CPU timer; no native/model/residual rebill |
| 5 | primary-full400-frozen-observer-v2-audit | ordinary GNU CPU timer; exact original audit output path |
| 6 | fixed-all400-adapted-score | ordinary GNU CPU timer; no model/HTTP/business/ledger calls |
| 7 | fixed-all400-adapted-score-audit | ordinary GNU CPU timer; every original proposal and metric payload checked |
| 8 | primary-all400-adapted-score | ordinary GNU CPU timer; no model/HTTP/business/ledger calls |
| 9 | primary-all400-adapted-score-audit | ordinary GNU CPU timer; every original proposal and metric payload checked |
| 10 | both400-original-lossless-archives-after-all-gates | ordinary GNU CPU timer; script and archive_case have no ledger accounting |

固定规范别名命令：

```bash
env PYTHONPATH=/cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-v1:/cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-v1/runtime/src:/cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-v1/runtime/tools PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 /cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/artifacts/jev-reader/http-env/bin/python /cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-v1/finalize_external_mem2act_predictions_v1.py /cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/stages-mem2act-v1/fixed-prefix-prediction400-v1-owner.json /cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/finalized-mem2act-v1/fixed-prefix-predictions /cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/finalized-mem2act-v1/fixed-prefix-prediction400-v1-closure.json
```

固定完整400观察器命令（使用原输出路径；普通CPU需加唯一GNU计时）：

```bash
env PYTHONPATH=/cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-v1:/cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-v1/runtime/src:/cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-v1/runtime/tools PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 /cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/artifacts/jev-reader/cuda-env/bin/python -u -c 'import json,runpy,sys,transformers,tokenizers; assert transformers.__version__=='"'"'4.52.3'"'"'; assert tokenizers.__version__=='"'"'0.21.4'"'"'; protocol=json.load(open('"'"'/cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-v1/protocol-before-public-task-projection-v1.json'"'"')); sys.path.extend(protocol['"'"'site_packages'"'"']); entry=sys.argv[1]; sys.argv=sys.argv[1:]; runpy.run_path(entry,run_name='"'"'__main__'"'"')' /cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-audit-execution-v2/audit_mem2act_predictions_execution_v2.py /cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-v1/protocol-before-public-task-projection-v1.json /cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/finalized-mem2act-v1/fixed-prefix-predictions /cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/stages-mem2act-v1/fixed-prefix-prediction400-v1-owner.json /cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/finalized-mem2act-v1/fixed-prefix-full400-audit-v1.json
```

实际全部门禁满足后的primary原owner命令（**不加GNUwrapper**）：

```bash
env PYTHONPATH=/cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-v1:/cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-v1/runtime/src:/cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-v1/runtime/tools PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 /cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/artifacts/jev-reader/http-env/bin/python -u /cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/frozen-mem2act-v1/own_external_mem2act_stage_v1.py /cra/memory/mx_memory/MiLAi-worktrees/a100-development-20261104/MiLAi-Lab/artifacts/a100-development-20261104/external-own-policy-v1/stages-mem2act-v1/primary-seed0-u32-prediction400-v1-plan.json
```

计划路径未变。命令引用当前原始owner；若原运行出现反思后NOT_RUN continuation，需按真实最终owner
与最早首结果祖先重解owner参数，规范别名保持所有400原首记录，不能更换失败输出。

## 评分与400任务的分组解释

评分仍由原frozen score_closed_mem2act_predictions_v1.py与audit_mem2act_scores_v1.py执行。
全部零/多个/invalid proposal与failed Host的原提议保留；正确intent不能把failed Host修成完成。
completed_strict要求原status=COMPLETED，参数F1和canonical-JSON BLEU1是既有MiLAi适配口径，
不冒充论文TA/F1/BLEU或leaderboard，也没有业务工具实际执行。

比较器已写好且只运行**结构预检**，真实指标分支必须等两方法的closure/fullSource/scoreaudit六门禁。
重建原400任务的引用图时，连接依据是声明的source IDs（包括缺失ID），以及命中完整session所包含的
全部原始source IDs；不能只连接已匹配session编号。第一次新观察器因此失败，修正的是观察逻辑，
原400任务与冻结341组件未改。341=291单任务＋45双任务＋2三任务＋2四任务＋1五任务组件。

它们不是400个独立用户，也不是341个独立实验：每任务可用同一个完整429session/16843turn bank，
实际策略还可能跨reference-session读取。后续只报告原400分母、任务配对增减与明确的参考组件平衡
描述，不计算query IID或组件独立性CI。无声明7、无匹配16、部分缺失3、缺失IDs11、schema-name
不一致1仍保留，不过滤或修补。Source/角色忠实和intent重叠也不等独立事实或泛化。

比较器的全量分支还会沿实际closure所有owner祖先累加whole/parent（包括保留失败段），
不会只报最后tail的CPU，也不会把其中native/load再加一次。目前没有实际800指标或成本结论。

## 原无损归档的结束条件

归档脚本只在两方法closure/fullSource/scoreaudit全部通过后运行。原case_archive.archive_case按固定
字节块保存，重建并逐字节比较成功后才移除对应raw runtime/capture snapshot；不使用SHA/指纹。
全部原first结果/driver/评分/首次Host元数据与final-input Store inventories仍保留，完整immutable
prepared common base必须留在所有case/档案目录之外。实际primary尚需这些fixed快照，不能提前归档。
原归档脚本及archive_case没有native ledger计量，属于普通CPU命令，实际结束后按唯一GNU计时结算。
GPU job区间与Host等待、本地NN、whole/parent、归档/存储和最后项目总成本分开，不重计。

当前所有prepared动作仍未派发。完整目标还需要fixed400闭合、primary400、两方法全审计/评分/归档，
实际空闲后费用结算、最终论文图表与全763行完成审计；不从本文或预检passed推断它们已完成。

## 全量指标闭合后的图表入口

[绘图入口](../tools/plot_a100_mem2act_native_comparison.py)已完成结构预检，当前没有生成
Mem2Act指标或图片。真正分支要求上述六个closure/Source/score门禁全通过，以及比较器的
全800主分支结果；再从两套原400评分逐项复核计数、task-macro F1/JSON-BLEU1和配对增减。
图中完成且严格匹配、任意Host状态的严格intent、原生执行状态和适配重叠指标分别展示，
没有IID/组件独立性CI，也不冒充原论文TA或实际业务执行结果。

预测费用面板只显示原生响应回调、已知tokens、实际返回NN决策/输入及全部ancestor的
整child＋已测parent CPU。固定采集与主策略重放有不同记录开销；它们不是受控延迟对照，
native/load已经包含在整child中。后续评分、归档、准备与完整项目成本仍在独立范围。

原completed0和IncompleteChatResponse失败2实际均有3个vllm_response/usage条目，
已知tokens分别9424、16831；Host捕获的delivered_model_requests条目却分别为3、2。
因此图与新比较元数据明确标为“响应回调”，保留错误/partial回调；不能以捕获条目数漏计
失败成本，也不能把共享generation准入数换名HTTP。冻结v2中旧decoded_provider_responses
字段逐字保留，未因此改变观察器、首结果、Source或400门禁。这两个例子的核对不证明全400。

- [核对与准备源码](../tools/prepare_a100_mem2act_closeout_handoff.py)
- [未来全量比较器](../tools/analyze_a100_mem2act_native_comparison.py)
- [完整计划当前证据](MILAI_A100_PLAN_CURRENT_EVIDENCE_20261109.md)
