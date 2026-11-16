# A100 LME Small固定前缀：原生结果、完整操作与调用成本

固定前缀的全451条首预测及原生评分已关闭，并通过完整Source/Reader输入审计和原生
评分/Judge请求审计。401条可评分回答中正确75条（75/401＝18.70%），另50条Reader
首失败未评分。全451条缺失边界为[75/451,125/451]＝[16.63%,27.72%]；原生
`native_complete_cohort_metrics`仍为null，不报告完整组的精确点分数。

本文保留固定前缀单方法结果。2026-11-09两方法预测/评分及完整操作与调用比较已见
[后续比较报告](MILAI_A100_LME_NATIVE_COMPARISON_20261109.md)；归档、Mem2Act及全项目成本
继续沿执行记录推进，不以单方法报告替代整个计划完成。

## 评分、失败和暴露范围

451个公有query来自已接触的200个Small历史及图像，保留共享历史关系，不能当作
451个独立用户或未见Small/Medium确认。协议是给定query取证，再交给冻结的独立
Reader及所需原生Judge；这不是自主Host结果，也不是原论文Reader/Judge模型复现。
此处的独立Reader指其与取证策略的职责分开，不表示独立人类评审或独立数据。

401条完成回答中有250条有效模型UNKNOWN回答，按benchmark原生规则计分。
50条`FAILED_READING`保留`UNSCORED_FAILED_READING`和空score，既不补UNKNOWN，
也不把执行失败用作负gold。原生非abstention已评分子集为62/291＝21.31%，
abstention子集为13/110＝11.82%；这些也都是条件子集口径。

50次Reader失败均为一次实际HTTP、输出达到冻结8192上限并以length结束，49次没有
final正文，另1次保留501字符截断正文。原生完成条件要求stop，故该部分正文仍未
转成完整预测或评分。失败请求的最大总预留为15,540 tokens，
小于65536上下文，全部实际prompt估算误差为零；这是输出未完成，不能称为输入溢出。
没有根据观察到的失败改变thinking、输出上限、Source或Reader，也没有重跑失败位置。

51个串行预测段只显式续行原生NOT_RUN尾部；全451个最终整记录等于最早已尝试祖先。
它们仍是451个首结果，不能将继承记录或段数当成新增任务/独立样本。

## 实际HTTP和已知用量

| 调用范围 | 实际HTTP | 已知prompt tokens | 已知completion tokens | 已知总tokens |
|---|---:|---:|---:|---:|
| Reader全451 | 451 | 1,683,622 | 1,182,893 | 2,866,515 |
| 其中50个Reader首失败 | 50 | 247,982 | 409,600 | 657,582 |
| 原生所需Judge | 130 | 64,731 | 109,499 | 174,230 |

失败行是Reader全451中的子集，不额外相加。Reader＋Judge实际共581次HTTP、
3,040,745已知总tokens。本批没有新增generation/embedding未知用量；
历史未知用量保持。401个分数中130个需要实际Judge，其他分数沿原生规则产生，
不补造缺少的Judge调用。每个调用的response usage、call usage与对应owner的准入/
已知token差值独立核对相符；此批两种计数相同不表示准入计数普遍等于HTTP次数。

## 完整检索动作与交付

| 选择/执行 | 次数 |
|---|---:|
| SEARCH选择及searched执行 | 902 |
| READ选择及opened执行 | 1804 |
| HANDOFF选择 | 451 |
| 全部控制决策 | 3157 |
| 实际操作返回 | 2706 |
| 返回packet中的original_source材料项 | 1804 |

每条query保留原生请求、完整合法菜单、选中动作的全部绑定及实际operation_result。
全451次检索都以policy_handoff结束，每次四个READ；无材料预算拒绝。无参数
HANDOFF直接结束控制循环，不生成operation_result，因此3157与2706是不同计数。
返回材料项含重复来源/范围，不等同唯一事实数、Source覆盖或正确使用率。

完整机械审计逐项核对9,364,144个Source值、3157个完整before恢复快照、451份
原生SDK交付上下文及451个完整Reader请求；角色、时钟、Store/Saver、应用/世界
及原始输入边界保留。该门槛证明Source/输入路径忠实，回答是否正确仍沿原生评分。

## 完整子进程、父CPU及计量边界

| 阶段 | 实际串行段数 | 完整子CPU＋已测父CPU秒 | 各owner实际wall之和秒 |
|---|---:|---:|---:|
| 固定前缀预测 | 51 | 38088.242489 | 48909.668 |
| 原生评分 | 1 | 35.873309 | 762.029 |

预测与评分的完整子CPU已包含相应客户端、Source/状态复制、捕获、本地原生调用及IO
相关工作，未包含Host服务端计算。固定基线实际本地NN为零、模型加载为零，因此没有learner GPU job区间；
这些完整CPU与wall也不能解释为纯神经推理耗时。不同段在不同服务时刻执行，wall之和
不是受控服务延迟。Host GPU0/1忙碌小时及货币成本未测，不填零。

全部52个owner已实际退出、父子进程消失且原生CPU已支付一次。完整子CPU已经包含
native、call CPU及residual，不能再次叠加这些嵌套计时。Source准备、离线审计、
分析/文档、存储/归档、训练和未计量作者/启动/检查/清理不在上表小计内；后者为
unknown_not_zero。全项目表需另纳入这些真实成本，不能把该小计当作完整项目总成本。
本文分析/文档CPU在下一合格空闲窗口支付；不在运行中的原生归档期间改写账本。

## 复核入口

- [紧凑原生指标、完整用量及成本边界](../data/manifests/a100-lme-fixed-native-results-20261108-v1.json)
- [全451条调用与操作普查代码](../tools/analyze_a100_lme_fixed_native_operations_cost.py)
- [整体执行进度](MILAI_A100_DEVELOPMENT_EXECUTION_20261104.md)

完整逐项位置、原始路径、动作绑定、usage、52段owner计量与祖先链保存在ignored
`artifacts/a100-development-20261104/lme-fixed-native-operations-cost-census-v1.json`。
可向一个尚不存在的新输出重现；代码不读取原始预算文件，不调用模型/HTTP，不写业务
或账本，不改写Source/首结果，不使用SHA或内容指纹。

```bash
python3 tools/analyze_a100_lme_fixed_native_operations_cost.py \
  artifacts/a100-development-20261104 \
  artifacts/a100-development-20261104/lme-fixed-native-operations-cost-census-reproduction-v1.json
```
