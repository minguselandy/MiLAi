# V02-14 最新 Goal v0.3 完成复验（2026-09-10）

结论：**最新文档限定的本地 D0–D7 交付已验证完成，无需补发模型请求或扩大实现范围。**
Client 0.1.4 仍仅为本地 opt-in helper；A0 默认、公开部署与 Schema NO-GO 不变。

本次完整读取 1,198 行最新 Goal，SHA256：
`92d1daf6cdb4c48ecef018759d3ad1aff39bd6e5b4a99291ae8478e615406b85`。
v0.3 新增的是状态、边界和成本分账说明，并明确将外部 Host 接线、线上 BGE、
公开发布/部署等留在后续范围。本次未用旧完成状态代替检查，也未把这些后续事项宣称已验证。

## 当前代码与证据

| 要求 | 本次检查的权威证据 | 结果与范围 |
| --- | --- | --- |
| D0 / 版本、历史与分区 | baseline manifest、安装 wheel SHA、H1 v1/v2 result/seal 与源码快照、v2 的 12 个封存输入文件 | 哈希一致；旧 517 次公开调用可分解复算；没有打开旧保护池 |
| D1 / T01–T09 | 当前 source binding/helper、边界单测、既有 PG 权限/撤销 receipts | 五态覆盖、请求/版本/游标、取得/呈现、有界并发有证据；子代理另在内存中强制乱序完成并检查返回归属 |
| D2 / T10–T14 | 当前 delivery checker、单测和两条真实澄清结果 | required/optional/type/enum/current input 与动作意图区分有效；歧义时实际提问且 calls 为空，不仅依赖结果标签 |
| D3 / T15–T16 | 两份旧 cost-replay SHA、零生成 reserve replay、实际跨进程预约测试 | 两案第 2 步 nonfinal 为 FINAL_ONLY，同输入 final 为 ALLOW；未推断答案改善；新累计 cap 仍为 null |
| D4 / T17–T19 | 固定 lexical 配置、两个方向的原始 query/公开调用 receipts、实际模型 payload | 不以 metadata hit 当呈现；query 未使用 gold；counterfactual 输出未送回模型 |
| D5 / T20–T25 | 16 个最终 H 阶段、原始 Note 保存/读取、cold binding、进程与时间区间、stage gate 复算 | 15 次交付与 1 次澄清正确；无文件的 Note 冷恢复成立；8 对新旧 PID 不同、无继承 messages，两个并发任务分别有真实区间重叠 |
| D6 / 六项产品化门 | 固定四 cluster 的全部 A0/H 和两个 LX 长任务、封存输入/源码、实际账本与冻结阈值 | 全部保留、无换题；阶段门重新计算通过；H4/4、A0 1/4、LX2/2，包含澄清而非参数分母混用 |
| D7 / SDK、兼容与交付 | 当前 SDK 模块、六份锁、全套静态/测试/构建、wheel 内容与 SHA、runbook | 本地 opt-in Client0.1.4 已交付；无默认接线、Runtime/权限/事务变更或迁移；不冒充新 wheel 真实 PG/外部 Host 效果 |
| T26–T28 | Host 排队测试、十个自有环境的当前 Docker/进程状态、目录权限和七批账本 | Host 有界拒绝已测；服务端饱和仍未验证。十个 API PID 均不存在、PG 容器均 exited，原始根目录均 0700 |
| 文档与最终十项回答 | [完整结果报告](MILA_V0214_HOST_RESULTS_20260909.md) §15 答复、Lab/Product 当前状态及索引、Client runbook | 交付、版本、回退、成本与局限相互一致；v0.3 Goal 和原始结果未改写 |

上述 D0–D4 由用户授权的子代理作有界只读复核，主代理独立负责 D5–D7、全部封存链与当前包检查。
子代理本次相关单测 59 passed，Ruff PASS；未启动模型或服务、未修改代码或旧证据。

## 本次实际重跑的工程检查

| 包 | pytest | 其他检查 |
| --- | --- | --- |
| Lab | 748 passed，9.96s | boundary、Ruff、mypy 39 文件、wheel/sdist PASS |
| Client | 209 passed，1.53s | locked Ruff、mypy 15 文件、wheel/sdist PASS |
| MCP | 385 passed / 7 skipped，26.96s | locked Ruff、mypy 21 文件、wheel/sdist PASS |
| hooks | 52 passed，0.34s | locked Ruff、mypy 6 文件、wheel/sdist PASS |
| OpenWorker | 176 passed，5.34s | locked Ruff、mypy 14 文件、wheel/sdist PASS |
| LangGraph | 5 passed，0.36s | locked Ruff、mypy 2 文件、wheel/sdist PASS |
| AutoGen | 6 passed，0.44s | locked Ruff、mypy 2 文件、wheel/sdist PASS |

Lab 命令为 `uv run milai-lab-check-boundary`、`uv run ruff check src tests tools`、
`uv run mypy src/milai_lab`、`uv run pytest -q`、`uv build`。
各适配器分别执行 `uv run --locked ruff check src tests`、`uv run --locked mypy`、
`uv run --locked pytest -q`、`uv build`。MCP 的 7 个跳过是可选 PG/auth calibration，
没有当作通过或擅自启用公网验收。

重新构建的 Client wheel SHA256 与原交付一致：
`58e5d82a1e82ccff1111bea28184ac2958ea62028cf2698e8ef1fb273cab38d4`。

## 账本与不变边界

七批实验逐一重算封存 manifest、输入文件和 executed-source 哈希，并从 Provider 请求/响应、
tokenize 与预约账本重新汇总：**133 请求 / 877,655 raw，unknown 0、对账差异 0**。
D5 六批 119/770,002，D6 一批 14/107,653；失败 v1/v2/v3 均保留。
本次新增实验模型请求 **0**、新增实验 raw **0**；检查/代理劳动与这些实验计数分开。
没有覆盖原有 result、manifest、stage-gate 或 final-terminal 文件。

第一次手动离线核对命令因 tools 模块导入路径缺失而退出；显式设置 Python 模块搜索路径后
重新执行成功。此诊断没有调用模型、创建分配或改变旧结果。

继续保留：D3 不证明答案提升；字符串覆盖不等于语义蕴含；H 的成本增加不是效率胜出；
本地 helper 8 KiB 串行 P95 的 5.43× 开销未改写。服务端饱和、SQL 并行、DB 等待、
远程/对抗性来源、大规模冷缓存、外部泛化、新 Client 外部接线及线上 BGE 效果均不作完成主张。
9 月 9 日公网 pin 仅作为有日期的既有记录，本次未重新探测或变更公网。

本次只补充该复验记录并重新构建本地包，没有修改业务实现、实验配置、Goal v0.3 或封存数据，
没有新增 State、Memory backend、发布、部署或 Schema freeze。
