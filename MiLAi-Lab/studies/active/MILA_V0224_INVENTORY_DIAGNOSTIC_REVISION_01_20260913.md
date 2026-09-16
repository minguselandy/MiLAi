# V0224 inventory成本诊断：观测修订01

本轮是原R02候选的受影响观测重验，不是第二个性能候选。当前工作点已通过测量校准但余量失败：前两次runtime准入24.50–24.65秒>18秒，其中inventory独占17.29–17.48秒；其私有解析/形状扫描/探针与回退/剩余引用处理份额未知。见[当前反思](../../docs/V0224_CURRENT_WORKPOINT_REFLECTION_20260913.md)。

只在新版本S中分解私有strict parse、eligibility scan、sentinel/fallback三类累计成本，按scope和外层span聚合，不保留逐文件轨迹或payload，不替换全局JSON/文件系统/SQL库。剩余inventory独占成本继续明确为未细分，不给它预命名的耗时份额。U继续安装原候选，私有helper不调用新探针或时钟。完整读取、哈希、两次观察、动态SQL/账务、原始异常与停止路径不变。

本轮新六个fresh roots，保留当前轮全部静态输入/源码/副本和57个历史账本的实际负担；机械root/episode/scope与派生initial hash之外语义不变。新binding/worker/parent/observer及局部回归需独立审查，实际constructor/PREP库存和初始当前账本需逐套核对，再冻结唯一合同。

固定顺序U/S、S/U、U/S，每位置一次、新冷进程、并发1；每个完整spawn至exit≤300秒，原参考Session仍60秒，五scope诊断保持首生成截断与原FAIL_CLOSED。没有模型、HTTP、设备或外部服务权限；工程本机协议例外不适用于本轮。全部六位置覆盖/语义/计时守恒独立通过，且配对S/U中位≤1.10后，才解释新分解。失败保留全部尝试/未运行，不扣除计量时间、不沿用旧1.0228、不重跑取快。

本轮不启动K3或Memory，也不降低18/90秒及完整矩阵门。成本分解完成后依据实际结果选择一个最小性能修订或提出新工作条件；若修改算法，另列版本并做受影响等价/负控、配对和完整门。原R02/current/K2合同、源码和证据保持原样。

开发与原始证据目录：`/cra/memory/mx_memory/evidence/v0224/20260913-a-diagnostic-v1`。当前只有开发草案，未封夹具、未校准、没有PASS。用户授权完整执行与代理审查继续适用；最终可执行范围以独立冻结记录为准。
