# WP0：依赖、源码与检查对应

范围为[后续改进计划](MILAI_NEXT_IMPROVEMENT_PLAN_20260927_v1.0.md)的C0工程验证。
状态：**IN_PROGRESS，尚未取得本次修复的远端CI结果。** 不涉及Host提示、实验算法、模型部署或Product行为。
实际Goal继续执行本计划；按用户最新要求，在当前任务结束后暂停Goal、发布总体实验报告。
[机器结果清单](../data/manifests/next-improvement-wp0-verification-20260927.json)明确分开已完成检查与待执行项。

## 首个断点与归因

基线main `9515017a5dfaba6b6e306fa778fd20f4383b6e35`，PR51 head
`055a0769c1ce75d128d6459ee25773587d9003ae`。分别使用独立锁定core环境执行同一命令
`uv run --no-sync mypy src/milai_lab`，均报14错误/7文件、检查110文件。
PR51的[远端失败原日志](https://github.com/minguselandy/MiLAi/actions/runs/36318522281)
与本地错误类别一致；该旧head的foundation专项成功，full composition跳过。

Observed：默认环境缺少langgraph、langchain_core、langmem、openai的可选依赖，
Mypy仍递归进入相关源码。Expected：每个活动模块有安装真实依赖的检查归属，核心协议在core环境独立检查。
竞争解释为main既有覆盖缺口、PR改变导入图、本地与CI依赖不一致。
相同锁与环境下main/PR产生同样错误，支持既有缺口；不是仅凭“出错文件没改”判断。

首次仅修类型命令后，core测试又出现两种既有前置缺口：external测试在顶层导入可选依赖；
历史MERIT适配测试依赖被Git排除的v7 freeze、原始arc/world和模型身份资产。
另外，Mem0实际SDK测试在缓存缺失时会skip，安装Python依赖不能证明该项已执行。
这些失败保留在本轮记录，不用减少收集数伪装修复。

## 小型检查矩阵

机器映射见[lab-verification-matrix.json](../configs/lab-verification-matrix.json)，
源码覆盖检查见[检查入口](../tools/check_verification_matrix.py)。
fast与full组合CI必须按相同归属执行。`pyproject.toml`和`uv.lock`的依赖版本不升级。

| 环境 | 依赖安装 | 类型检查归属 | 测试归属 |
| --- | --- | --- | --- |
| core | `--frozen --dev --python 3.11` | contracts、analysis、harness、scorers及两个boundary入口；PR51存在时单独检查纯protocol | 无可选依赖的公开测试；PR51的纯协议合同实际执行 |
| foundation | core＋`--group baseline-langmem` | 全包发现＋原exclude模块的显式glob | LangMem、provenance、freshness、M1、ODR、LSA、application、read-probe |
| external | core＋`--group baseline-langmem --group external-mem0` | mem0_native与mem0_identity | 原生Mem0 add/search、稀疏向量、实体关联和重启等模拟HTTP集成 |
| 历史私有资产 | 保留的v7原始资产与现有core依赖 | 源码仍由上述静态环境负责 | 精确列出的4项MERIT历史资产合同；公共CI不声称执行，本地结果单列 |

在当前main源码上，core直接22个文件；foundation默认发现110个，加显式36个，
其中33个恢复原exclude，3个重合，合并覆盖全部143个活动Python源码；external直接2个。
这些是源码集合数，不是测试数，不能相加称171个独立模块。
PR51多出的protocol由core和foundation分别承担相应检查。
仅检查exclude正则不足以解释导入遍历，因此各环境还实际执行其Mypy命令。

Luna准备的独立环境均为CPython3.11.13、pytest8.4.2、uv0.8.3。
三个core各安装60包，foundation96包，external138包；其后external的固定NLP资产另记。
锁文件SHA256为`62b762bd2573d194d38677d6fcd9a74ff788cd5c6d64585987c1b2c79891c5d1`。
安装receipt、包清单和原始检查日志保持ignored；不提交虚拟环境、缓存或模型资产。

Mem0检查的既有NLP前置已实际补齐：`en_core_web_sm`3.8.0的26个文件全部匹配旧v26
hash（15231350 bytes）；固定`Qdrant/bm25` revision
`22b8d2af71a76161e18dd432d2cee0eefa66e412`从原缓存复制，20个文件全部匹配
（25242 bytes，含原来声明的两个空兼容文件）。Mem0锁定commit及7个来源文件hash也匹配。
使用[旧环境manifest](../data/manifests/milai-external-memory-v26-environment-receipt.json)校验，
不把该历史manifest本身当成此次安装成功证据。新本地receipt另保存在ignored制品目录。
Sol随后实际运行external四项：**4 passed、0 skipped**，模型/embedding请求由MockTransport替代。
这不构成第二模型家族验证，也不是新增真实实验结果。

## 已有证据与待闭环项

PR51在独立core环境执行`uv run --no-sync pytest -q tests/unit/test_lsa_controller_contract.py`，
结果71 passed；其中35项是旧/新结构差分场景，不能再累计成另外35项或真实任务样本。
Root审阅完整controller差异、纯protocol及合同测试：容量预占、候选/响应顺序、
U/maintenance/A、解析错误、事件角色及兼容导出保持原设计。合成Bank/model不代替真实Store集成。
局部审阅没有发现额外运行行为变更；PR仍须完成所需CI与正常审阅后再决定合并。

本地main/PR初始复现与71项检查仅保留当时工具回执，未另存日志文件。
不为补造日志重跑已通过检查；远端旧错误日志已保存并有公开run链接。
后续C0新检查日志位于ignored临时目录`/tmp/milai-next-c0-checks/`。

新矩阵的foundation八个文件实际执行144 passed、0 skipped；四项历史私有资产合同
在复制原freeze并保留原arc/world/模型身份检查的本地环境中为4 passed、1 deselected。
那1项无私有资产测试仍属于core公共门禁，没有丢弃整份测试文件。
另修正一处旧schema精确断言，使其包含main运行源码早已存在的`literal_uses`字段；
未改变运行schema，也未放宽精确字段集合。

公共core为5198项收集：**5171 passed、19 skipped、8 deselected**，耗时756.94秒。
19项skip中，1项需要历史固定Host SDK wheel；18项需要未入Git的V0213 tokenizer/model证据。
精确文件/行号/数量见机器清单。8项deselect是4项本地MERIT合同和4项既有regression；
这两类数量分别记录，不将它们加到公共core通过数。
历史SDK配置的wheel SHA为`58e5d82a1e82ccff1111bea28184ac2958ea62028cf2698e8ef1fb273cab38d4`。
当前Product源码离线构建的wheel与该旧pin不同，因此旧合同由原制品在本地单独验证，
原身份专项已在本地得到1 passed（2.40秒）；公共CI明确不执行该历史身份。
没有改写旧pin，也没有新增当前SDK路线或Product源码修改。

全Ruff、core/foundation/external Mypy、两个Lab边界、1728项Archive校验、矩阵检查、
工作流YAML解析均通过。文档字节冻结后执行最终wheel/sdist构建，结果与hash由发布回执单列，
避免将sdist自身hash写回其包含的文档产生循环。当前尚待新提交的实际fast与full composition结果。
全局ignore_missing_imports、仅扩大exclude、整文件importorskip和必需job跳过均不作为通过。

## 成本、发布与回滚

本轮真实generation/embedding调用为0；模拟HTTP测试不计为真实模型请求。
连续实验账本仍为2768次生成、3420333 generation tokens、18746 embedding tokens；
SHA256为`a9d4c681e2bee395c170a4672b4895a442522df47951c9a043e9f6b3a32e3580`。
开发代理、CI、普通依赖与NLP资产准备开销与实验token口径分开。

C0独立发布，不混入C1重构或C2 CRUD行为修复；回滚代码不改变实验数据库或世界状态。
原计划字节、所有历史结果、源码锁、失败与旧未跟踪v27草稿保留。
完成绿色CI只关闭工程门槛，完整研究计划的其余工作仍按[执行记录](MILAI_NEXT_IMPROVEMENT_EXECUTION_GOAL.md)推进。
