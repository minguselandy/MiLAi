# HiAgent 单任务真实执行与证据

日期：2026-09-14。算法 `hiagent-terminal-v0.1`，终端适配修复版 `hiagent-terminal-adapter-v0.1.1`。

执行[实施文档](MILA_HIAGENT_BASELINE_IMPLEMENTATION_20260914.md)第 7 节后，状态为 **LIVE_MECHANISM_OBSERVED / NATIVE_TASK_FAILED / ENGINEERING_COMPLETE**。真实 tokenizer、HTTP、Actor、摘要、终端和原生 verifier 已接通；这条轨迹验证了分段和摘要进入后续输入，未证明方法效果优于普通 Agent，也未验证真实检索。工程回归已取得完整终态，当前 4479 项测试全部覆盖：4478 通过、1 项可选依赖跳过。

## 本次边界与接口修复

本次用户要求“详细阅读并执行”实施文档，据此单独分配一个已有隔离任务 `cancel-async-tasks`，总计最多 64 次模型生成，Actor、摘要和检索决策共同计数，每次输出容量 4096。该题是既有池中首个软件实现任务，过去已暴露，属于开发任务；不是新留出题或重新筛选的胜出样本。保留原生 900 秒 Agent 时限、1 CPU / 2048 MiB / 0 GPU、串行调用。未续用关闭 Goal 的额度。

第一次调用产生不存在的 `write` 动作，被 Host 在派发前拒绝。其 659 输入、222 输出、合计 881 tokens 已结算；环境动作数为 0，原生评分为空。保留[失败轨迹](/cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/live)，不把它计成 0 分或从成本中删除。

通用接口修复仅在工具说明中明确完整动作集合，以及文件编辑通过 `exec` 完成；没有增加 `write` 工具、题目提示、固定子目标边界、摘要缓存或自动解析重试。新增显式 `--hiagent-max-calls 1..64`，默认仍为 64。修复尝试只使用本次原额度剩余的 63 次；Host 和 Provider 都采用该上限。[运行前分配](../../data/manifests/hiagent-terminal-live-20260914.json)保留两个尝试及修复依据，两份原始分配快照均在证据目录。

修复尝试的实际命令如下；`--root` 必须使用不存在的新目录。命令作为本次重现记录，未分配再次执行额度。

```bash
PYTHONPATH=/cra/memory/mx_memory/MiLAi-Lab/src:/cra/memory/mx_memory/MiLAi-Lab/tools \
  /cra/memory/mx_memory/benchmarks/complex-native-20260914/harbor-venv/bin/python \
  tools/run_workspace_native.py \
  --task /cra/memory/mx_memory/benchmarks/complex-native-20260914/terminal-bench-2-2fd12b88aafdd04a52c298e3940bcb189f9766d6/cancel-async-tasks \
  --root /cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/live-repair \
  --order HIAGENT --hiagent-max-calls 63 --force-build \
  --compose-override /cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/task-network.json \
  --artifact /app/run.py
```

Harbor 固定 0.23.0，任务固定 commit `2fd12b88aafdd04a52c298e3940bcb189f9766d6`。本次重新核对全部该题非 solution 文件的 Git blob；沿用原 Dockerfile 与已有本地基础镜像，并先核对独立子网不重叠。容器审计与删除终态见[任务及清理证据](/cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/task-and-cleanup-audit.json)。未启动服务、操作 GPU、改变产品默认或写入产品数据。

## 方法实际做了什么

修复后 11 次 Actor 决策形成 10 个模型声明的子目标，执行 10 条终端命令后提交 final。Host 发起 45 次独立摘要，9 次后续 Actor 输入含过去段摘要；当前段仍保留真实动作与观察。第 1 至第 9 段分别被摘要 9、8、7、6、5、4、3、2、1 次。这正是首版每轮重摘要的实际成本，未缓存、未减免。

[逐调用审计](/cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/live-audit.json)逐一核对：发送载荷与 Provider 文件及 SHA-256 一致；用量与原始 HTTP 响应一致；模型返回与 Host 返回一致；摘要请求只含当时过去段已经返回的动作／观察；摘要正文确实取代该段详细正文进入后续 Actor 输入；工具观察与真实回执一致。审计脚本 [audit_live.py](/cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/audit_live.py)只离线读取证据，不发模型请求。

模型实际完成了文件写入、导入、自建并发测试和取消测试；10 条命令中有 3 次与此前命令完全重复。模型也把一次自建测试传参错误转成了实现修订：用户合同要求 callable，测试却传入 coroutine 对象。后续摘要有时准确记录该差别，有时把“写入代码成功”扩展成“正确支持两类输入”。因此摘要是可出错的解释，不能作为完成证书。

本次 **retrieve 为 0，摘要失败回退为 0**。不得把模拟检索测试转写成真实检索已验证。原始日志与完整回执在 [live-repair](/cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/live-repair)，未置于任务容器的模型可见日志中。

## 原生结果与完整成本

原生 verifier 正常运行，**5 PASS / 1 FAIL，reward = 0**。失败为任务数超过并发上限时的取消清理；这是有效任务失败，不是验证器依赖安装失败。模型自建的 `task.cancel()` 检查通过，不能覆盖原生进程中断检查。模型最后的完成表述不改变评分。[原生检查回执](/cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/live-repair/trials/cancel-async-tasks-0-hiagent/verifier/test-stdout.txt)

| 成本范围 | 生成 | 输入 tokens | 输出 tokens | 总 tokens |
| --- | ---: | ---: | ---: | ---: |
| 初次接口失败，Actor | 1 | 659 | 222 | 881 |
| 修复后 Actor | 11 | 17,500 | 2,141 | 19,641 |
| 修复后摘要 | 45 | 27,060 | 2,571 | 29,631 |
| 全部尝试 | **57** | **45,219** | **4,934** | **50,153** |

全部 57 次生成均结算，pending 与用量越界为 0；余下 7 次关闭，不自动续跑。修复后摘要占 45/56 次调用、29,631/49,272 tokens（约 60.1%）。HTTP 生成等待累计 38.53 秒；两次 trial wall time 分别 18.48、84.25 秒；Agent 执行分别 2.18、43.72 秒；修复后工具累计 3.34 秒。工程准备、回归及本开发代理的用量另列，不能把 trial 时间冒充完整项目时间。辅助 tokenizer/model HTTP 不计作模型生成；没有美元费率，美元成本未计价。

该题旧 NOTE/REVIEW 成绩属于另一时点、政策和实验；本次没有重新执行同期普通 Agent 对照，不据此计算配对净收益。当前结论是方法机制已在真实任务启动，但未通过该任务全部要求，不签发无条件 `LIVE_USABLE` 或产品能力结论。

## 工程验收

接口修复后邻近 **86 PASS**，含新增的总预算缩减／Actor 与摘要共用上限测试；边界检查、全仓 ruff、全包 mypy（41 个源文件）与构建通过。[检查记录](/cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/checks-final.json)

全仓 `uv run pytest -q` 使用同一进程完整结束，**4473 PASS / 1 SKIP，exit 0，4040.54 秒**。唯一跳过为既有可选 Host SDK wheel 未安装。日志：[regression.log](/cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/regression.log)。旧版 2279 PASS 后中断的记录继续作为历史保留，本次没有中断、缩减或重启该回归。

运行启动时收集 4474 项；随后新增 5 项预算测试，当前清单为 4479 项。86 项最终源码邻近测试与主回归重合 81 项；去重后当前全部 4479 项均有终态，合计 **4478 PASS / 1 SKIP，0 FAIL / 0 ERROR / 0 缺项**。[逐项覆盖核对](/cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/regression-coverage.json)以 JUnit 的测试身份逐项匹配当前收集清单，没有重复计数。

回归期间改动仅三个工具文件和一个测试文件，核心算法未改；这些接口改动由修复后的邻近测试和真实 trial 验证，[源码差异清单](/cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/source-delta.json)保留具体范围。当前运行代码与修复 trial 快照一致。[源码核对](/cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/final-runtime-source-audit.json)。文档与清单定稿后再次构建 wheel / sdist，记录见[交付构建](/cra/memory/mx_memory/evidence/hiagent-execution-20260914-8VRvQ3/delivery-build.json)。任务容器和本次回归进程均已退出。

## 后继只提出一处算法改变

这条真实轨迹支持提出一个可检验的后继版本：把“每轮重写各闭合段摘要”替换为“新工具回执到达后，维护一份当前决策依据”。维护调用读取上一版依据与新动作／真实回执，对受影响判断执行保留、缩小适用范围或撤回，并保存来源回执引用；Actor 接收更新后的依据，原始轨迹仍可按需读回。调用和输入成本继续全部入账。

例如，自建取消测试仅支持其实际使用的取消方式，不能被提升为所有中断方式都已验证；传参不符合用户合同的测试失败，也不自动证明实现接口应改变。这是从本次已见轨迹提出的假设，不能把本题再当该改法的未见迁移题。该后继尚未实现、分配实验或声称新颖；需另行与普通 Agent/review、HiAgent 及相关已有方法比较。当前 HiAgent 基线没有混入这一改法，旧 `KEEP_SIMPLE` 结论保持。
