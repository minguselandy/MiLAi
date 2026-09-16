# V0224 当前工作点：校准有效，余量不足

当前测量校准已获独立最终审查通过；Gate A 尚未通过，K3/B–E未运行。

K2单次55-scope配对保持原参考和诊断停止语义，完整子进程从753.294781秒降至670.586224秒（减少10.9796%）。这个结果没有内部计时，不能推导18秒准入余量。

随后六个新冷进程按U/S、S/U、U/S各一次运行，完整父进程394.449331秒、外层394.54秒，实际全部退出0。S/U中位1.022818806≤1.10。三次S的前两次运行时准入并集为24.646946075、24.584550743、24.498026138秒，均超过原18秒门。不能扣除观测开销补成通过，也不需要启动完整K3再重复已经可证实的余量失败。

现有连续span可把这两次准入归属的工作分开：inventory独占17.2936–17.4837秒，首次读取约3.22–3.24秒、收口读取约3.00–3.03秒，公开read_json子类仅0.4242–0.4320秒。私有JSON解析、形状扫描、递归余量探针/回退和引用遍历都包含在inventory中，其内部份额尚未测得。公开JSON子类不是完整JSON成本；仅消除这约0.43秒不可能弥补6.50–6.65秒的缺口。

下一步应在新版本中区分inventory内部纯计算，再选择有依据的最小修订。静态可讨论重复路径规范化和私有形状扫描，但现有计时不能证明某一项主导。若增加观察点，旧S/U校准不自动覆盖新探针；必须保留严格U、计时守恒、原始60秒Session及新探针开销校准。历史数据、失败实例和已封源码均不修改或复用。任何新候选仍要重新验证受影响语义、动态负控、完整矩阵和原余量门。

证据：

- [K2独立配对审查](/cra/memory/mx_memory/evidence/v0224/20260913-a-k2-v1/independent-k2-pair-review.json)。
- [当前校准合同](/cra/memory/mx_memory/evidence/v0224/20260913-a-current-v1/contract.json)，SHA256 `41e815526ae91d1ca90dce51ab3bfeb10adeb9eb2afa42e8d4a92c7e93135411`。
- [校准原始审计](/cra/memory/mx_memory/evidence/v0224/20260913-a-current-v1/calibration-audit-draft.json)、[实际外层退出](/cra/memory/mx_memory/evidence/v0224/20260913-a-current-v1/calibration-envelope-tool-terminal.json)。

测量校准通过是仪器资格，余量失败是当前工作点结论；两者均不代表主Goal完成。模型/实验HTTP仍0，Memory有效分母0。工程本机协议测试的独立附加范围尚未执行，不混入实验零网络合同。

- [最终独立校准/余量审查](/cra/memory/mx_memory/evidence/v0224/20260913-a-current-v1/currentcalibration-review.json)，SHA256 `45c714746e7f2e4e13c26abffbd4cc82324d1569bbe626995021e28039050b4e`。
- [运行时操作成本表](/cra/memory/mx_memory/evidence/v0224/20260913-a-current-v1/current-runtime-operation-cost-map.json)。
