# MiLAi V1.2 PLAN-2 最终报告

独立确认覆盖 1,500 题与 620 个原生组。重复测量覆盖 150 题与 58 个完整组。主读出实付 19,500 次 Reader 请求，重复实付 1,950 次。同一冻结采集池用于三个实际训练种子。SHA 校验关闭。

## 四项结论

| 命题 | 状态 | 宏质量差及 95% 区间，分 | 相对节省及 95% 区间 | Holm 调整 p |
| --- | --- | --- | --- | --- |
| 后续训练相对匹配 W | not established | +1.17 [-0.39, +2.76] | +5.21% [+3.53, +6.82]% | 0.22675 |
| M1 相对配平宽 M0 | not established | -1.25 [-2.77, +0.24] | -24.77% [-27.55, -21.83]% | 1 |
| 部署输入效率 | not established | +2.48 [+0.49, +4.55] | -36.26% [-39.04, -33.64]% | 1 |
| 端到端加速 | not established | +2.48 [+0.49, +4.55] | -14.56% [-17.68, -11.42]% | 单独时延条件 |

前三项采用 5,000 次来源内原生组配对抽样与冻结的单侧 Holm 家族。相对节省前三行指 Reader 输入，端到端行采用实测任务时延加策略加载摊销。时延配对完整性为 true。规划备择下联合通过率估计为 13.0%。

| 比较 | 种子或敏感性 | 质量差及 95% 区间，分 | Reader 输入节省及 95% 区间 |
| --- | --- | --- | --- |
| 后续训练相对匹配 W | 11 | +0.37 [-1.54, +2.32] | +0.04% [-1.84, +1.91]% |
| 后续训练相对匹配 W | 29 | +1.93 [+0.10, +3.87] | +7.49% [+5.48, +9.51]% |
| 后续训练相对匹配 W | 47 | +1.22 [-0.71, +3.13] | +8.09% [+6.36, +9.71]% |
| 后续训练相对匹配 W | 种子和组联合抽样 | [-0.71, +2.97] | [+0.36, +9.04]% |
| M1 相对配平宽 M0 | 11 | -0.44 [-2.65, +1.71] | -14.98% [-19.90, -9.82]% |
| M1 相对配平宽 M0 | 29 | -1.95 [-4.00, +0.13] | -25.00% [-28.53, -21.51]% |
| M1 相对配平宽 M0 | 47 | -1.38 [-3.23, +0.41] | -34.28% [-37.23, -31.46]% |
| M1 相对配平宽 M0 | 种子和组联合抽样 | [-3.11, +0.61] | [-33.99, -15.20]% |
| 部署输入效率 | 11 | +1.49 [-0.81, +3.76] | -43.75% [-46.92, -40.83]% |
| 部署输入效率 | 29 | +3.23 [+1.00, +5.52] | -32.92% [-36.13, -29.86]% |
| 部署输入效率 | 47 | +2.71 [+0.56, +4.84] | -32.12% [-34.84, -29.55]% |
| 部署输入效率 | 种子和组联合抽样 | [+0.20, +4.73] | [-43.43, -30.59]% |

## 原生运行计量

| 条件 | 位置 | 实付 | 格式及其他非正常评分状态 | Provider 输入 token 合计 | Provider 输出 token 合计 | 已知 cached token 合计 | 有 inline 计时的位置 | p50 毫秒 | p95 毫秒 | 加载毫秒合计 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| M0-seed11 | 1500 | 1500 | 9 | 2,492,540 (1500 题) | 85,948 (1500 题) | 未知 (0 题) | 1500 | 2,124.5 | 4,360.0 | 89,530.0 |
| M1-seed11 | 1500 | 1500 | 13 | 2,446,374 (1500 题) | 83,035 (1500 题) | 未知 (0 题) | 1500 | 2,135.9 | 4,760.5 | 89,067.4 |
| wide-M0-seed11 | 1500 | 1500 | 5 | 1,870,014 (1500 题) | 84,093 (1500 题) | 未知 (0 题) | 1500 | 1,628.8 | 3,400.7 | 86,858.2 |
| M0-W-seed11 | 1500 | 1500 | 5 | 2,421,120 (1500 题) | 81,007 (1500 题) | 未知 (0 题) | 1500 | 2,539.3 | 3,840.7 | 84,036.8 |
| M0-seed29 | 1500 | 1500 | 11 | 2,288,009 (1500 题) | 84,374 (1500 题) | 未知 (0 题) | 1500 | 1,938.3 | 3,754.1 | 84,245.0 |
| M1-seed29 | 1500 | 1500 | 4 | 2,685,085 (1500 题) | 84,745 (1500 题) | 未知 (0 题) | 1500 | 2,446.3 | 5,449.5 | 87,816.0 |
| wide-M0-seed29 | 1500 | 1500 | 6 | 1,929,437 (1500 题) | 86,014 (1500 题) | 未知 (0 题) | 1500 | 1,640.2 | 3,485.5 | 86,955.3 |
| M0-W-seed29 | 1500 | 1500 | 4 | 2,419,389 (1500 题) | 81,046 (1500 题) | 未知 (0 题) | 1500 | 2,514.5 | 3,865.7 | 84,773.8 |
| M0-seed47 | 1500 | 1500 | 6 | 2,243,703 (1500 题) | 86,095 (1500 题) | 未知 (0 题) | 1500 | 1,903.1 | 3,699.2 | 84,012.4 |
| M1-seed47 | 1500 | 1500 | 5 | 2,766,157 (1500 题) | 85,773 (1500 题) | 未知 (0 题) | 1500 | 2,633.3 | 5,557.5 | 87,977.8 |
| wide-M0-seed47 | 1500 | 1500 | 3 | 1,883,671 (1500 题) | 85,462 (1500 题) | 未知 (0 题) | 1500 | 1,660.7 | 3,481.4 | 87,298.3 |
| M0-W-seed47 | 1500 | 1500 | 3 | 2,421,264 (1500 题) | 81,292 (1500 题) | 未知 (0 题) | 1500 | 2,538.2 | 3,872.3 | 96,574.0 |
| B* | 1500 | 1500 | 5 | 1,822,847 (1500 题) | 78,014 (1500 题) | 未知 (0 题) | 1500 | 1,989.4 | 3,313.0 | 0.4 |

各来源计量覆盖、TTFT、动作、重复诊断及原生窗口的 CPU 与墙时保留在可复查收据内。GPU 指标来自已采样区间。

[原生正式结果](/data/milai-experiments/20261119-memory-control-v12/E-confirmation-results.json) [全量复算](/data/milai-experiments/20261119-memory-control-v12/plan2-native-confirmation-full-readback.json) [资源结算](/data/milai-experiments/20261119-memory-control-v12/plan2-confirmation-final-native-compute-settlement.json) [功效登记](/data/milai-experiments/20261119-memory-control-v12/E-confirmation-power.json)

## 开发与训练证据

C∪D 含 24,000 个不同状态，两轮 P 含 12,000 个不同状态。本次共核对 34 个含 W 的正式 DEV 条件。冻结终态为 O。

[开发门槛](/data/milai-experiments/20261119-memory-control-v12/plan2-development-gates-native-readback.json) [V1.1 与 W](/data/milai-experiments/20261119-memory-control-v12/plan2-baselines.json) [三种子 DEV](/data/milai-experiments/20261119-memory-control-v12/plan2-native-all-three-seed-architecture-paired-DEV605.json) [P 与 R-only 的冻结选择](/data/milai-experiments/20261119-memory-control-v12/D-policy-stage-complete.json) [实验矩阵](/data/milai-experiments/20261119-memory-control-v12/experiment-matrix.json) [checkpoint 索引](/data/milai-experiments/20261119-memory-control-v12/selected-checkpoints.json)

## 离线复算命令

```sh
cd /data/milai-experiments/20261119-memory-control-v12/source-2d91d00f/MiLAi-Lab
export PYTHONPATH=src:tools CUDA_VISIBLE_DEVICES='' HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
/data/milai-experiments/20261116-small-memory-control/verification-env-v1/bin/python /data/milai-experiments/20261119-memory-control-v12/verify-native-confirmation-readback.py --root /data/milai-experiments/20261119-memory-control-v12 --phase complete --wait-seconds 0 --output /tmp/milai-plan2-confirmation-readback.json
```
