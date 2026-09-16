# 表示与结构变体的五臂编排

MILA-V02-05 v0.25工程增量。现有协调器可以从同一个G完成点独立启动A、B、B表示变体、
B结构变体。变体经过公开保存、新Host进程恢复和实际请求记录，不在发送前临时替换字符串。
本次使用脚本G与网络不可用的模拟模型传输，不是正式D4/D5或模型泛化结果。

## 实现

`memory_variants`是可选配置，缺省仍为G/A/B。配置必须声明两个变体各自改变L1或L2中的
一层，以及具体变换。初始来源准备和G后新增来源沿用同一公开捕获/metadata核验函数，
现在覆盖五个独立项目。所有续做分支从G复制完整文件，保留相同的新旧合法来源。

`v02_variant_plan.py`只处理确定性的实验变换，不解释业务内容：

- 文本与`{"text": "完整原文"}`包装之间转换，只证明包装兼容；不是字段分布泛化。
- JSON业务正文键前移/后移、非保留键换序，保持值及保留字段位置。
- 删除预先声明的无语义空首尾包装；缺失、非空、数值0、位于正文内部或保留协议字段均拒绝。
- 实际产物不适用、缺少指定正文键或没有产生声明的结构变化，返回NOT_APPLICABLE。
  不构造空包装、不重做G、不消耗模型分配或保存State来填补机会。

`v02_memory_variants.py`先核对母本版本及当前来源资格，保留母本，再生成独立变体文件。
变体全文通过公开Evidence捕获并读回验证；公开State仅改变选定层及所需版本/定位/引用。
另外一层和无关payload保留。原有来源资格仍约束变体，新的捕获回执不能替代原有支持。
L1 JSON中正式来源引用沿用B相同的分叉绑定；正文里像ID的字符串不做替换。

Host沿用正常保存、冷启动、按需文件读取和每次发送前资格检查。B及两个变体均按State优先
装配，不暗中预载L2。种子保存现在分开记录operation和GET head，未知操作或head变动不启动
该分支。启动异常也会关闭已分配的本地会话记录，远端未知usage不被清零或假装结算。

比较器只将具有匹配请求hash、dispatch及已结算回执的请求作为已确认输入，分别核对
恢复State、bootstrap和进入后续请求的L2页。只捕获到材料、只写出请求文件或未发送的工具
返回不算已呈现。页offset/hash/正文与来源核对，Bootstrap必须匹配恢复State。
比较同时保留原始摘要及仅将正式来源引用映回G身份的摘要，不改正文来抹平差异。

## 真实公开接口与模拟Host执行

配置：`configs/v02-variant-branches-engineering.json`。
成功目录：`artifacts/v02-e2e-generality/variant-branches-20260907b/`。
Product仍为`84ccec2a5ffeb7813667c378a59df593e13c4cc47b5cba815f75ff3ac1931dc4`，
运行前和终态审计通过；Product代码、公网服务与共享模型未改。

| 工程链 | 表示变体 | 结构变体 | 恢复与输入的观察 |
|---|---|---|---|
| c1 | L2文本包装 | L1正文前移 | L1键序被持久化处理消除；恢复值确实进入模拟请求 |
| c2 | L1文本包装 | L2正文后移 | 新L2文件及页内容差异保留并进入后续模拟请求 |
| c3 | L2文本包装 | L1非保留键换序 | L1键序被持久化处理消除；不能称模型位置稳健 |
| c4 | L1文本包装 | L2删除声明空首尾包装 | 必要值、0和完整正文保持；变换后的页进入后续模拟请求 |

四条链使用工程fixture，不是四个留出家族案例。每条有一个真实退出的脚本G进程，
以及A/B/两个变体共4个新Host进程。实际存储使用独占Runtime/PG与公开HTTP MCP/Hook/SDK；
只有模型传输使用`httpx.MockTransport`，无法退回网络Provider。模拟Host每臂先读L2再交付，
该脚本选择不证明Agent自主查源或理解。

共20个已确认State身份、44条来源Evidence、8个独立变体产物、16个冷Host进程、32个
已确认模拟completion请求。L1/L2选择层及全文件保真通过；两个L1键序差异被消除，另两个
L2结构差异保留。`terminal-audit.json`核对版本/引用/原始文件、模拟传输、逐请求hash及
全部进程终态；后续只读重算补充引用归一化对比，原运行输入和比较记录均未覆盖。

首次目录`variant-branches-20260907a/`在c1的A启动前失败：测试替身缺少STDOUT常量。
原错误、9条已捕获来源与2份已确认State保留；A本地分配根据进程未启动且无Provider
dispatch的直接证据补记终态。修复替身并增加负控后另建b目录，不重写失败记录。
此失败没有模拟或真实模型请求。JSON正式引用绑定修正有直接单元回归；本次真实结构fixture
的内层evidence_refs为空，因此不把该单元回归冒充带非空内层引用的公开保存效果。

新增真实模型、真实tokenize、付费调用均为0。模拟usage只用于控制器回归，32次模拟
completion和模拟tokenize不能加入真实token账本或用于质量/价格比较。四条成功工程链
含准备和清理共188.232秒；首次失败30.181秒，另列。变体准备耗时记录在各臂中，也被当前
launcher的deadline覆盖，不能再与会话墙钟重复相加。真实HTTP总次数未汇总，metadata、
初始化、握手和来源准备仍各有开销，不填零。正式成本边界仍待冻结验收。

## 回归与边界

实际执行：

```bash
uv run python tools/check_v02_variant_branches.py --root artifacts/v02-e2e-generality/variant-branches-20260907b --config configs/v02-variant-branches-engineering.json
uv run milai-lab-check-boundary
uv run pytest
uv run ruff check src tests tools
uv run mypy src/milai_lab
uv build
```

29项新回归覆盖计划拒绝、首尾/Unicode/换行保真、保留字段、非空删除负控、不适用无分配、
引用绑定、seed UNKNOWN/head推进、启动失败终态、未呈现材料及实际页/请求核对。
完整Lab497 passed（5.35秒）；Ruff格式修正后全量Ruff通过，边界、mypy 30文件、构建通过。
Product源码未变，不重复其全量回归。5个独占PG容器exit0、无OOM，全部客户端/API/worker
已结束，卷保留。没有迁移或Canonical权限变化；禁用可选计划可保留原三臂流程。

原D5任务资料manifest SHA仍为
`7e884ae847e44acbfe7101aa7f331b0b257d1171a15100633caf8742f3748b8a`。
资料中的structure只有扰动名称，缺少层/格式及按kind需要的正文键或无语义包装声明；
不能隐式指定字段、把Markdown强包装成结构机会，或将task.json直接交给runner。
下一步补清逐任务绑定与执行配置入口，实际G仍须验证机会，不满足时保留缺口。
当前没有把这四条fixture升格为正式开发/留出链。

完整D0/D3、正式D4/D5仍未完成；混合负载保存/公平出口及SIM12解释失败继续独立保留。
Schema为0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE。
