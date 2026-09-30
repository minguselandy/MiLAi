# v13.1 执行记录

日期：2026-09-30。状态：ACTIVE / P1/P2机械原型通过，首6故事3/6；完整规划未完成。

## 授权与原始范围

用户明确要求详细阅读并执行 [原始规划](MILAI_DEVELOPMENT_EXPERIMENT_PLAN_v13_1.md)。
原规划481行已完整阅读，原文 bytes 保持，SHA256
`e67cc5253cbe6967d935cc5c9b9f4453c731665d1937d9049e323c10e54dc9ca`。
DESIGN_ONLY 是原始设计快照，当前用户授权允许执行。旧v10暂停只描述其历史范围。
完整目标保持P0–P8；第16节只界定首批P0/P1/P2，不能以完成首批替代完成全部计划。
[60项要求清单](../data/manifests/v13-1-requirements.json)记录所需直接证据，未证明的要求不计完成。

## 当前身份与盘点

隔离分支 `feat/lab-usability-v13-1-20260930`，工作树
`/cra/memory/mx_memory/MiLAi-worktrees/development-experiment-v13-1`；基于实际fetch核对的
main `255dfcde5d73b9fc800cdd7f866460a09908c12f`。原入口checkout落后103提交，保持其
未跟踪草稿原样。未重新运行历史实验，未覆盖历史冻结或错误记录。

[P0原始身份核查](../data/manifests/v13-1-p0-freeze.json)包含实际容器、HTTP模型目录、
启动参数、挂载的模型配置/tokenizer/template哈希。7860、7862分别是既有JSON-action和
native-tools Qwen3.6-35B-A3B-FP8服务；7861为bge-m3。均实际GET200，上下文分别65536/8192。
`server_info`返回404，不能声称从该接口取得完整运行配置；改用实际容器参数与本地文件核对。
[完整权重身份](../data/manifests/v13-1-model-weights.json)已流式核查43个实际挂载权重文件，
合计39734807990 bytes，逐文件SHA256及前后size/mtime稳定；读取耗时121.84秒。
本地完整内容身份不等于可推断的upstream revision标签。

原连续账本仍位于原checkout `MiLAi-Lab/artifacts/ser-v20/budget.json`，核对SHA256
`7f0e54548dcbebe1325ebbac4a0fc4441f20efc949cd16be4084c3f9b8aeda43`。
起始累计6145次generation/11407086 generation tokens/416930 embedding tokens，unknown0。
只读GET、源码核查和开发代理消耗不记作实验generation；本批R1已新增28generation/35132tokens。
最新连续6173generation/11442218tokens/416930embedding，unknown0；详见[R1结果](V13_1_D0_R1_RESULTS.md)。
后续每次形成、Host、embedding、恢复和失败重试继续原账本，不建立零起点替代账本。
价格与总费用上限未知，保持null；正式预算由pilot的实际分布决定。

[暴露清单](../data/manifests/v13-1-source-exposure.json)组合旧v8/v9、v10、LSA和contextual历史
来源，并从11个历史registry/selection/audit元数据计算保守并集：90个case ID、61个原source ID、
120个来源组引用、66个完整历史hash及65个MERIT seed。按source ID、完整历史hash及来源组
排除；MERIT0–4已曝光，5–64旧规划reserved不能
凭假设重新当未见。正式集和pilot均未选取，不查看正式问题或gold。

## 第一批固定开发输入

[D0运行输入](../data/fixtures/v13-1-d0-normal.json)在看到新候选成绩前冻结24例，保存、召回、
更新、scope、对象继续、重启各4例。每类第1例组成预定6故事。新公共消息由新进程读取相同
持久资源；更新同时检查历史版本，scope覆盖群体/一次性/项目/无日期锚点，业务检查原始
物品key、同一预订和无重复效果。这些是开发样本，不能转为独立论文测试。

[离线rubric](../data/diagnostics/v13-1-d0-rubric.json)与运行输入分文件，runtime不可读取。
语义是否正确需要核查原始回答、来源/版本和真实world，不能只用关键词命中宣告成功。
使用门槛预定>=22/24，同时owner泄漏0、虚假保存成功0；所有失败/未知仍留在分母。
正常检查不隐藏注入故障：对象组起始label服务可用，另外的partial/unknown真实故障归入P5。

P1/P2实现复用SDK Store/checkpointer、ApplicationWorld与既有模型/工具组合。Source由实际用户
或工具事件确定性捕获，模型只选来源/内容；Ref-only与Field-grounded独立，先只绑定公开回执
status、label_status。正文保留原提案且无语义真值保证；真实ref不等于正确字段。SQLite第一批
只声称实测范围，不能宣称通用跨系统exactly-once、Postgres CAS或生产并发。

## 外部baseline当前核查

[baseline核查](../data/manifests/v13-1-baseline-audit.json)记录源码、依赖pin和实际调用路径。
主foundation环境缺少外部依赖，已找到既有专用环境：Mem0安装版本2.1.0、commit
f8082a7345dadd9e042ebbc40b57b1498c8f6d63；SimpleMem环境含LanceDB0.25.3/pylance0.39.0，其实际159个源码文件已核对固定commit
db80b6a7c591e0ea730a058e9f5fc4eb06572299；Mem0实际149个文件也已核对安装源码身份。这些只证明安装/源码身份，不计作六项微型行为验收通过。

Mem0旧after_turn只摄入用户+最终助手；新的MERIT completed路径实际从checkpoint截取闭合回合，
保留role/id/content/tool_calls/tool_call_id/name/status后调用add_archive。该函数使用明确标记为
历史数据的JSON包，不改其原生抽取算法；实际HTTP wire与保留效果待P3固定微型运行验证。
不能由after_turn一个函数推断全部历史表，也不能把静态调用路径称为实测模型保真。

SimpleMem实际speaker保留role，content保留tool字段，timestamp映射；原event/id只在trace
source_mapping，未进入native dialogue content。P3须独立冻结lossless trace-equal载体或明示
限制；此处不把可追踪ID和实际模型可见原ID混为一谈。没有新增安装、下载或服务部署。

## 门禁与待办

| 阶段 | 当前证据 | 状态 |
|---|---|---|
| P0 | main/服务/ledger/基线安装/暴露引用有直接只读核查 | PARTIAL；完整候选身份和正式分组还未冻结 |
| P1 | 原6故事12消息真实终态、独立进程SDK持久核对；3/6通过 | PARTIAL；召回/更新/scope存在断点，24门槛未通过 |
| P2 | 服务/Agent16、legacy9、architecture217，静态/矩阵通过 | SCOPED_MECHANICAL；实际模型fields为空，效果未证明 |
| P3 | 实际摄入调用路径与外部环境身份核查 | PARTIAL；微型行为验收NOT_RUN |
| P4–P8 | 原始scope/恢复/pilot/正式矩阵/第二家族/统计/复现/初稿要求完整保留 | NOT_RUN |

Engineering-valid、Usability-ready和Research-supported均未验收。Product保持NO_GO。
完整计划不能因负结果或预算耗尽自动改写为较小目标；后续按实际证据更新每项要求。

## 反思记录 0：已有字段真实性断点

观察：v10 R2错误业务ID和错误完成正文曾真实持久化；当前v12整理只保留旧语义。
最早断点：没有把业务操作字段与真实工具观察建立受限支持关系。竞争解释：引用合法性、
字段支持和正文推断可能各自不同；仅提示严谨也可能解释改进，不能预设新结构独立有效。
最小区分实验：同一真实ref+错误status/label_status提案在Ref-only与Field-grounded分别提交，
保留原提案与拒绝回执；后续实际Agent与Prompt-only对照另冻，不以固定提案回放代替Agent收益。
不变：旧默认、公开工具合同、来源/owner、两字段支持范围；不增加Attention或reviewer。
否定条件：合法字段被大量误拒或Ref-only同等减少传播，必须修合同或缩小贡献。
本次零模型机械诊断不发生generation；真实D0每消息最大12调用/4096输出/并发1，全部计费。
